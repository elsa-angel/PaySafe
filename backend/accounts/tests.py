from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

User = get_user_model()

VALID = {
    'full_name': 'Asha Menon',
    'email': 'Asha@Example.com',
    'password': 'Str0ng-Passw0rd!',
    'confirm_password': 'Str0ng-Passw0rd!',
}


class AuthApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # reset throttle counters
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get('/api/auth/csrf/')
        self.csrf = self.client.cookies['csrftoken'].value

    def post(self, url, data):
        return self.client.post(url, data, format='json', HTTP_X_CSRFTOKEN=self.csrf)

    def signup(self, **overrides):
        return self.post('/api/auth/signup/', {**VALID, **overrides})

    # --- signup ---
    def test_signup_creates_user_with_hashed_password(self):
        res = self.signup()
        self.assertEqual(res.status_code, 201)
        self.assertNotIn('password', res.data)
        user = User.objects.get(email='asha@example.com')
        self.assertEqual(user.first_name, 'Asha Menon')
        self.assertNotEqual(user.password, VALID['password'])
        self.assertTrue(user.password.startswith('pbkdf2_'))
        self.assertTrue(user.check_password(VALID['password']))

    def test_signup_duplicate_email_case_insensitive(self):
        self.signup()
        res = self.signup(email='ASHA@example.COM')
        self.assertEqual(res.status_code, 400)
        self.assertIn('email', res.data)
        self.assertEqual(User.objects.count(), 1)

    def test_signup_validation(self):
        cases = {
            'full_name': ('', 'full_name'),
            'email': ('not-an-email', 'email'),
            'password': ('short', 'password'),
        }
        for field, (value, key) in cases.items():
            body = {**VALID, field: value}
            if field == 'password':
                body['confirm_password'] = value
            res = self.post('/api/auth/signup/', body)
            self.assertEqual(res.status_code, 400, field)
            self.assertIn(key, res.data, field)

    def test_signup_rejects_numeric_and_common_passwords(self):
        for pw in ('123456789012', 'password123'):
            res = self.signup(password=pw, confirm_password=pw)
            self.assertEqual(res.status_code, 400)
            self.assertIn('password', res.data)

    def test_signup_password_mismatch(self):
        res = self.signup(confirm_password='Different-Passw0rd!')
        self.assertEqual(res.status_code, 400)
        self.assertIn('confirm_password', res.data)

    def test_signup_requires_csrf(self):
        res = self.client.post('/api/auth/signup/', VALID, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(User.objects.count(), 0)

    # --- login ---
    def test_login_logout_flow(self):
        self.signup()
        self.assertEqual(self.client.get('/api/auth/user/').status_code, 403)

        res = self.post('/api/auth/login/', {'email': 'asha@example.com', 'password': VALID['password']})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['email'], 'asha@example.com')
        self.assertNotIn('password', res.data)
        self.assertIsNotNone(User.objects.get(email='asha@example.com').last_login)

        me = self.client.get('/api/auth/user/')
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data['full_name'], 'Asha Menon')

        self.csrf = self.client.cookies['csrftoken'].value  # rotated on login
        self.assertEqual(self.post('/api/auth/logout/', {}).status_code, 204)
        self.assertEqual(self.client.get('/api/auth/user/').status_code, 403)

    def test_login_failures_share_one_generic_message(self):
        self.signup()
        wrong_pw = self.post('/api/auth/login/', {'email': 'asha@example.com', 'password': 'nope-nope-nope'})
        no_user = self.post('/api/auth/login/', {'email': 'ghost@example.com', 'password': 'nope-nope-nope'})
        self.assertEqual(wrong_pw.status_code, 401)
        self.assertEqual(no_user.status_code, 401)
        self.assertEqual(wrong_pw.data, no_user.data)

    def test_login_inactive_user_rejected(self):
        self.signup()
        User.objects.filter(email='asha@example.com').update(is_active=False)
        res = self.post('/api/auth/login/', {'email': 'asha@example.com', 'password': VALID['password']})
        self.assertEqual(res.status_code, 401)

    def test_login_validation(self):
        self.assertEqual(self.post('/api/auth/login/', {'email': '', 'password': ''}).status_code, 400)
        self.assertEqual(self.post('/api/auth/login/', {'email': 'bad', 'password': 'x'}).status_code, 400)

    def test_login_is_throttled(self):
        for _ in range(10):
            self.post('/api/auth/login/', {'email': 'a@b.com', 'password': 'x'})
        self.assertEqual(self.post('/api/auth/login/', {'email': 'a@b.com', 'password': 'x'}).status_code, 429)


class ProfileApiTests(APITestCase):
    NEW_PASSWORD = 'An0ther-Str0ng-Pass!'

    def setUp(self):
        cache.clear()
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get('/api/auth/csrf/')
        self.csrf = self.client.cookies['csrftoken'].value
        self.user = User.objects.create_user(
            username='asha@example.com', email='asha@example.com',
            password=VALID['password'], first_name='Asha Menon',
        )

    def sign_in(self):
        res = self.client.post(
            '/api/auth/login/', {'email': 'asha@example.com', 'password': VALID['password']},
            format='json', HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(res.status_code, 200)
        self.csrf = self.client.cookies['csrftoken'].value

    def send(self, method, url, data):
        return getattr(self.client, method)(url, data, format='json', HTTP_X_CSRFTOKEN=self.csrf)

    def change(self, **overrides):
        body = {
            'current_password': VALID['password'],
            'new_password': self.NEW_PASSWORD,
            'confirm_new_password': self.NEW_PASSWORD,
            **overrides,
        }
        return self.send('post', '/api/auth/change-password/', body)

    # --- profile ---
    def test_profile_update_requires_authentication(self):
        res = self.send('patch', '/api/auth/user/', {'full_name': 'Hacker'})
        self.assertIn(res.status_code, (401, 403))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Asha Menon')

    def test_profile_update_changes_name_only(self):
        self.sign_in()
        res = self.send('patch', '/api/auth/user/', {
            'full_name': '  Asha   Menon Nair ', 'email': 'evil@example.com', 'is_staff': True,
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['full_name'], 'Asha Menon Nair')
        self.assertNotIn('password', res.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Asha Menon Nair')
        self.assertEqual(self.user.email, 'asha@example.com')
        self.assertFalse(self.user.is_staff)

    def test_profile_update_validation(self):
        self.sign_in()
        for name in ('', ' ', 'A', 'x' * 151):
            res = self.send('patch', '/api/auth/user/', {'full_name': name})
            self.assertEqual(res.status_code, 400, repr(name))
            self.assertIn('full_name', res.data)

    # --- change password ---
    def test_change_password_requires_authentication(self):
        res = self.change()
        self.assertIn(res.status_code, (401, 403))

    def test_change_password_success_keeps_session(self):
        self.sign_in()
        res = self.change()
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('password', str(res.data).lower().replace('your password has been updated', ''))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW_PASSWORD))
        self.assertFalse(self.user.check_password(VALID['password']))
        self.assertTrue(self.user.password.startswith('pbkdf2_'))
        self.assertEqual(self.client.get('/api/auth/user/').status_code, 200)

    def test_change_password_wrong_current_rejected(self):
        self.sign_in()
        res = self.change(current_password='totally-wrong-1')
        self.assertEqual(res.status_code, 400)
        self.assertIn('current_password', res.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(VALID['password']))

    def test_change_password_mismatch_and_weak_and_same(self):
        self.sign_in()
        self.assertIn('confirm_new_password', self.change(confirm_new_password='nope').data)
        self.assertIn('new_password', self.change(new_password='123', confirm_new_password='123').data)
        same = self.change(new_password=VALID['password'], confirm_new_password=VALID['password'])
        self.assertIn('new_password', same.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(VALID['password']))

    def test_change_password_required_fields(self):
        self.sign_in()
        res = self.send('post', '/api/auth/change-password/', {})
        self.assertEqual(res.status_code, 400)
        for field in ('current_password', 'new_password', 'confirm_new_password'):
            self.assertIn(field, res.data)

    def test_new_password_works_for_login_old_does_not(self):
        self.sign_in()
        self.change()
        self.send('post', '/api/auth/logout/', {})
        self.csrf = self.client.cookies['csrftoken'].value
        old = self.send('post', '/api/auth/login/', {'email': 'asha@example.com', 'password': VALID['password']})
        self.assertEqual(old.status_code, 401)
        new = self.send('post', '/api/auth/login/', {'email': 'asha@example.com', 'password': self.NEW_PASSWORD})
        self.assertEqual(new.status_code, 200)
