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
