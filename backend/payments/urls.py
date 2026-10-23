from django.urls import path

from . import views

urlpatterns = [
    path('', views.PaymentListCreateView.as_view(), name='payments'),
    path('<str:transaction_id>/', views.TransactionDetailView.as_view(), name='payment-detail'),
    path('<str:transaction_id>/continue/', views.ContinueView.as_view(), name='payment-continue'),
    path('<str:transaction_id>/cancel/', views.CancelView.as_view(), name='payment-cancel'),
    path('<str:transaction_id>/verify-otp/', views.VerifyOtpView.as_view(), name='payment-verify-otp'),
    path('<str:transaction_id>/resend-otp/', views.ResendOtpView.as_view(), name='payment-resend-otp'),
]
