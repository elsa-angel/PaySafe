import { apiRequest, ensureCsrfCookie } from './api'

export const authService = {
  init: () => ensureCsrfCookie(),

  signup: ({ fullName, email, password, confirmPassword }) =>
    apiRequest('/api/auth/signup/', {
      method: 'POST',
      body: {
        full_name: fullName,
        email,
        password,
        confirm_password: confirmPassword,
      },
    }),

  login: ({ email, password }) =>
    apiRequest('/api/auth/login/', { method: 'POST', body: { email, password } }),

  logout: () => apiRequest('/api/auth/logout/', { method: 'POST' }),

  currentUser: () => apiRequest('/api/auth/user/'),

  updateProfile: ({ fullName }) =>
    apiRequest('/api/auth/user/', { method: 'PATCH', body: { full_name: fullName } }),

  changePassword: ({ currentPassword, newPassword, confirmNewPassword }) =>
    apiRequest('/api/auth/change-password/', {
      method: 'POST',
      body: {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_new_password: confirmNewPassword,
      },
    }),
}
