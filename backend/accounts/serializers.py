from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

User = get_user_model()

FULL_NAME_MAX_LENGTH = User._meta.get_field('first_name').max_length


def normalize_email(value):
    return value.strip().lower()


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user. Never exposes the password hash."""

    full_name = serializers.CharField(source='first_name', read_only=True)

    class Meta:
        model = User
        fields = ('id', 'full_name', 'email', 'date_joined', 'last_login', 'is_active')
        read_only_fields = fields


class SignupSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=FULL_NAME_MAX_LENGTH, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    confirm_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_full_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError('Please enter your full name.')
        return value

    def validate_email(self, value):
        email = normalize_email(value)
        # The email doubles as the username, so one lookup covers both fields.
        if User.objects.filter(username__iexact=email).exists() or \
                User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return email

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': ['Passwords do not match.']}
            )
        candidate = User(
            username=attrs.get('email', ''),
            email=attrs.get('email', ''),
            first_name=attrs.get('full_name', ''),
        )
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        # create_user hashes the password with Django's configured hasher.
        return User.objects.create_user(
            username=validated_data['email'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data['full_name'],
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        return normalize_email(value)


class ProfileUpdateSerializer(serializers.Serializer):
    """Editable profile fields. Email is deliberately not editable."""

    full_name = serializers.CharField(max_length=FULL_NAME_MAX_LENGTH, trim_whitespace=True)

    def validate_full_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError('Please enter your full name.')
        return value

    def update(self, instance, validated_data):
        instance.first_name = validated_data['full_name']
        instance.save(update_fields=['first_name'])
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    confirm_new_password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Your current password is incorrect.')
        return value

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_new_password']:
            raise serializers.ValidationError(
                {'confirm_new_password': ['Passwords do not match.']}
            )
        if attrs['new_password'] == attrs['current_password']:
            raise serializers.ValidationError(
                {'new_password': ['Your new password must be different from the current one.']}
            )
        user = self.context['request'].user
        try:
            validate_password(attrs['new_password'], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})
        return attrs

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])  # hashed by Django
        user.save(update_fields=['password'])
        return user
