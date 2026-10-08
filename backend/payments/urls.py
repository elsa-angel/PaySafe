from django.urls import path

from . import views

urlpatterns = [
    path('', views.PaymentListCreateView.as_view(), name='payments'),
    path('<str:transaction_id>/', views.TransactionDetailView.as_view(), name='payment-detail'),
]
