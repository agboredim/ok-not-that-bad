from itertools import product
from urllib import response
from django.shortcuts import render, get_object_or_404
from api.filters import ProductFilter
from rest_framework.decorators import api_view, action
from .serializers import *
from storeapp.models import *
from api.serializers import OrderSerializer, CreateOrderSerializer, UpdateOrderSerializer
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.mixins import CreateModelMixin, RetrieveModelMixin, DestroyModelMixin
from rest_framework.viewsets import ModelViewSet, GenericViewSet, ViewSet
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from api import serializers
from rest_framework import viewsets
from api.flutterwave import initiate_payment
import requests
from api.serializers import OrderSerializer, CreateOrderSerializer, UpdateOrderSerializer
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View 
import logging
import json
import hmac
import hashlib
from django.http import JsonResponse
from rest_framework import status
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from geopy.distance import geodesic
from django.shortcuts import render, redirect, HttpResponse
from django.contrib.auth import authenticate,login,logout
from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from .serializers import PasswordResetSerializer, PasswordResetConfirmSerializer
import uuid
from django.conf import settings

SHOP_LOCATION = (6.60247, 3.30721)

logger = logging.getLogger(__name__)
User = get_user_model()


def initiate_payment(amount, email, order_id):
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "email": email,
        "amount": int(float(amount) * 100),  # Paystack expects amount in kobo
        "reference": str(uuid.uuid4()),
        "callback_url": f"https://mb-shawarma-bite.ng/shawarma.html/?o_id={order_id}",
        "metadata": {
            "order_id": order_id,
            "customer_email": email,
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response_data = response.json()
        return Response(response_data)

    except requests.exceptions.RequestException as err:
        print("Payment initialization failed:", err)
        return Response({"error": str(err)}, status=500)




class ProductsViewSet(ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'description']
    ordering_fields = ['old_price']
    pagination_class = PageNumberPagination


class CategoryViewSet(ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ReviewViewSet(ModelViewSet):
    serializer_class = ReviewSerializer

    def get_queryset(self):
        return Review.objects.filter(product_id=self.kwargs["product_pk"])

    def get_serializer_context(self):
        return {"product_id": self.kwargs["product_pk"]}


class CartViewSet(CreateModelMixin, RetrieveModelMixin, DestroyModelMixin, GenericViewSet):
    queryset = Cart.objects.all()
    serializer_class = CartSerializer


class CartItemViewSet(ModelViewSet):
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return Cartitems.objects.filter(cart_id=self.kwargs["cart_pk"])

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AddCartItemSerializer
        elif self.request.method == 'PATCH':
            return UpdateCartItemSerializer
        return CartItemSerializer

    def get_serializer_context(self):
        return {"cart_id": self.kwargs["cart_pk"]}


class OrderViewSet(ModelViewSet):
    http_method_names = ["get", "patch", "post", "delete", "options", "head"]

    def create(self, request, *args, **kwargs):
        """Creates an order and includes delivery price in total."""
        serializer = CreateOrderSerializer(data=request.data, context={"user_id": self.request.user.id})
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        order.save()
        serializer = OrderSerializer(order)
        return Response({
            "message": "Order created successfully",
            "subtotal": order.subtotal,
            "delivery_fee": order.delivery_fee,
            "total_price": order.total_price,
            "order": serializer.data
        })

    @action(detail=True, methods=['POST'])  
    def pay(self, request, pk=None):
        """Initiates payment for the most recent order placed by the user."""
        order = Order.objects.filter(owner=request.user).order_by('-placed_at').first()
        if not order:
            return Response({"error": "No orders found for this user."}, status=status.HTTP_404_NOT_FOUND)

        amount = order.total_price
        email = request.user.email
        order_id = str(order.id)

        return initiate_payment(amount, email, order_id)

    @action(detail=False, methods=["POST"])
    def confirm_payment(self, request):
        """Handles payment confirmation and updates the order status."""
        order_id = request.data.get("o_id")
        if not order_id:
            return Response({"error": "Order ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = Order.objects.get(id=order_id)
            order.pending_status = "C"  # Confirmed
            order.save()
            serializer = OrderSerializer(order)
            return Response({
                "success": True,
                "msg": "Payment was successful",
                "data": serializer.data
            })
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

    def get_permissions(self):
        if self.request.method in ["PATCH", "DELETE"]:
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CreateOrderSerializer
        elif self.request.method == 'PATCH':
            return UpdateOrderSerializer
        return OrderSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Order.objects.all()
        return Order.objects.filter(owner=user)


class ProfileViewSet(ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer
    parser_classes = (MultiPartParser, FormParser)

    def create(self, request, *args, **kwargs):
        name = request.data["name"]
        bio = request.data["bio"]
        picture = request.data["picture"]

        Profile.objects.create(name=name, bio=bio, picture=picture)

        return Response("Profile created successfully", status=status.HTTP_200_OK)

def index(request):
    return render(request, 'index.html',)

def address_detail(request):
    return render(request, 'address.html',)


def order_list(request):
    search_query = request.GET.get('search', '')

    if search_query:
        orders = Order.objects.filter(transaction_ref__icontains=search_query)
    else:
        orders = Order.objects.all()

    return render(request, 'order.html', {'orders': orders})


def order_detail_view(request, order_id):
    order = get_object_or_404(Order, id=order_id)

    address = order.address if hasattr(order, 'address') else None
    

    return render(request, 'order_detail.html', {'order': order, 'address': address})


class ProductViewSet(ViewSet):
    """
    A ViewSet to group products by categories.
    """

    @action(detail=False, methods=['get'], url_path='grouped-by-category')
    def grouped_by_category(self, request):
        categories = Category.objects.all()
        response_data = {}

        for category in categories:
            products = Product.objects.filter(category=category)
            serializer = ProductSerializer(products, many=True)
            response_data[category.name] = serializer.data

        return Response(response_data)


class AddressViewSet(viewsets.ModelViewSet):
    queryset = Address.objects.all()
    serializer_class = AddressSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


def loginpage(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, "Login successful!")
            return redirect("index")
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()

    return render(request, "loginpage.html", {"form": form})

def logoutpage(request):
    logout(request)
    return redirect('index')

class DeliveryFeeEstimateView(APIView):
    def post(self, request):
        serializer = DeliveryFeeEstimateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        address_id = serializer.validated_data.get("address_id")

        try:
            address = Address.objects.get(pk=address_id)
        except Address.DoesNotExist:
            return Response({"error": "Address not found."}, status=status.HTTP_404_NOT_FOUND)

        if not address.latitude or not address.longitude:
            return Response({"error": "Address is missing location coordinates."}, status=status.HTTP_400_BAD_REQUEST)

        # Coordinates: warehouse in Lagos
        warehouse_location = (6.5244, 3.3792)
        user_location = (address.latitude, address.longitude)

        try:
            distance_km = geodesic(warehouse_location, user_location).km
        except Exception as e:
            return Response({"error": "Error calculating distance.", "details": str(e)}, status=500)

        base_delivery_fee = Decimal(1000)
        distance_fee = Decimal(50) * Decimal(distance_km)
        order_value_fee = Decimal(0.05) * Decimal(5000)  # Replace 5000 with actual order subtotal if needed

        delivery_fee = base_delivery_fee + distance_fee + order_value_fee

        # Peak hour surcharge
        current_hour = datetime.now().hour
        if 17 <= current_hour <= 20:
            delivery_fee += Decimal(500)

        delivery_fee = round(delivery_fee, 2)

        return Response({"estimated_delivery_fee": delivery_fee}, status=status.HTTP_200_OK)

# api/serializers.py
from rest_framework import serializers
import uuid

class DeliveryFeeEstimateSerializer(serializers.Serializer):
    address_id = serializers.UUIDField()