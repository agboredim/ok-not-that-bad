"""
ecommerce URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
"""

from django.contrib import admin
from django.urls import path, include
from api import views
from django.conf.urls.static import static
from django.conf import settings
from api.views import *

urlpatterns = [
    path('admin/', admin.site.urls),

    # Your app's API routes
    path("api/", include("api.urls"), name="api"),

    # Djoser auth (includes password reset, registration, etc.)
    path("auth/", include('djoser.urls')),           # <-- includes reset endpoints
    # Optional: add if you use JWT login/logout
    path("auth/", include('djoser.urls.jwt')),       # <-- only needed if using JWT login

    # Other views
    path('index/', views.index, name="index"),
    path('order/', order_list, name='order_list'),
    path('order/<int:order_id>/', order_detail_view, name='order_detail'),
    path('address/', address_detail, name='address_detail'),
    path('logoutpage/', views.logoutpage, name='logoutpage'),
    path('', views.loginpage, name='loginpage'),

    # Delivery fee estimation API
    path('api/delivery-fee/estimate/', DeliveryFeeEstimateView.as_view(), name='delivery_fee_estimate'),
]

# Serve media files
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
