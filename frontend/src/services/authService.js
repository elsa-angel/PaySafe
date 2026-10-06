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
}
