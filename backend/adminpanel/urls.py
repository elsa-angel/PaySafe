from django.urls import path

from . import views

urlpatterns = [
    path('overview/', views.OverviewView.as_view(), name='admin-overview'),
    path('fraud-statistics/', views.FraudStatisticsView.as_view(), name='admin-fraud-statistics'),
    path('users/', views.AdminUserListView.as_view(), name='admin-users'),
    path('users/<int:pk>/', views.AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('users/<int:pk>/status/', views.AdminUserStatusView.as_view(), name='admin-user-status'),
    path('users/<int:pk>/transactions/', views.AdminUserTransactionsView.as_view(), name='admin-user-transactions'),
    path('transactions/', views.AdminTransactionListView.as_view(), name='admin-transactions'),
    path('transactions/<str:transaction_id>/', views.AdminTransactionDetailView.as_view(), name='admin-transaction-detail'),
    path('reports/<str:kind>/', views.ReportView.as_view(), name='admin-report'),
]
