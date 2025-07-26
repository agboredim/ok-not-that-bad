from importlib.resources import read_binary
from itertools import product
from django.db import transaction
from datetime import datetime
from rest_framework import serializers
from  storeapp.models import *
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
import logging
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from datetime import datetime




class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["category_id", "title", "slug", "products"]


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [ "id", "name", "description","image", "category", "slug", "inventory", "price"]
    
    category = CategorySerializer()

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["id", "date_created", "name", "description"]
    
    def create(self, validated_data):
        product_id = self.context["product_id"]
        return Review.objects.create(product_id = product_id,  **validated_data)


class SimpleProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id","name", "price"]
        
        
        

class CartItemSerializer(serializers.ModelSerializer):
    product = SimpleProductSerializer(many=False)
    sub_total = serializers.SerializerMethodField( method_name="total")
    class Meta:
        model= Cartitems
        fields = ["id", "cart", "product", "quantity", "sub_total"]
        
    
    def total(self, cartitem:Cartitems):
        return cartitem.quantity * cartitem.product.price
    

class AddCartItemSerializer(serializers.ModelSerializer):
    product_id = serializers.UUIDField()
    
    def validate_product_id(self, value):
        if not Product.objects.filter(pk=value).exists():
            raise serializers.ValidationError("There is no product associated with the given ID")
        
        return value
    
    def save(self, **kwargs):
        cart_id = self.context["cart_id"]
        product_id = self.validated_data["product_id"] 
        quantity = self.validated_data["quantity"] 
        
        try:
            cartitem = Cartitems.objects.get(product_id=product_id, cart_id=cart_id)
            cartitem.quantity += quantity
            cartitem.save()
            
            self.instance = cartitem
            
        
        except:
            
            self.instance = Cartitems.objects.create(cart_id=cart_id, **self.validated_data)
            
        return self.instance
         

    class Meta:
        model = Cartitems
        fields = ["id", "product_id", "quantity"]





class UpdateCartItemSerializer(serializers.ModelSerializer):
    # id = serializers.IntegerField(read_only=True)
    class Meta:
        model = Cartitems
        fields = ["quantity"]


class CartSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    items = CartItemSerializer(many=True, read_only=True)
    grand_total = serializers.SerializerMethodField(method_name='main_total')
    
    class Meta:
        model = Cart
        fields = ["id", "items", "grand_total"]
        
    
    
    def main_total(self, cart: Cart):
        items = cart.items.all()
        total = sum([item.quantity * item.product.price for item in items])
        return total


class OrderItemSerializer(serializers.ModelSerializer):
    product = SimpleProductSerializer()
    class Meta:
        model = OrderItem 
        fields = ["id", "product", "quantity"]
        

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.ReadOnlyField()
    delivery_price = serializers.ReadOnlyField()
    total_price = serializers.ReadOnlyField()

    class Meta:
        model = Order 
        fields = ['id', "placed_at", "pending_status", "owner", "items", "subtotal", "delivery_price", "total_price"]



class CreateOrderSerializer(serializers.Serializer):
    cart_id = serializers.UUIDField()

    def validate_cart_id(self, cart_id):
        # Validate that the cart exists and is not empty
        if not Cart.objects.filter(pk=cart_id).exists():
            raise serializers.ValidationError("This cart_id is invalid")
        elif not Cartitems.objects.filter(cart_id=cart_id).exists():
            raise serializers.ValidationError("Your cart is empty")
        return cart_id

    def save(self, **kwargs):
        with transaction.atomic():
            cart_id = self.validated_data["cart_id"]
            user_id = self.context["user_id"]

            # Get the most recent address for the user
            try:
                address = Address.objects.filter(user_id=user_id).latest('created_at')
            except Address.DoesNotExist:
                raise serializers.ValidationError("User address not found.")

            if not (address.latitude and address.longitude):
                raise serializers.ValidationError("User address missing coordinates.")

            # Create order and assign the address
            order = Order.objects.create(owner_id=user_id, address=address)

            # Add order items
            cartitems = Cartitems.objects.filter(cart_id=cart_id)
            orderitems = [
                OrderItem(order=order, product=item.product, quantity=item.quantity)
                for item in cartitems
            ]
            OrderItem.objects.bulk_create(orderitems)

            # Warehouse coordinates
            warehouse_location = (6.5244, 3.3792)  # Lagos, Nigeria
            user_location = (address.latitude, address.longitude)

            # Calculate distance in km
            distance_km = geodesic(warehouse_location, user_location).km

            # Base delivery fee
            base_delivery_fee = Decimal(1000)

            # Distance-based delivery fee (₦50 per km)
            distance_fee = Decimal(50) * Decimal(distance_km)

            # Order value fee (5% of order subtotal)
            subtotal = sum([item.quantity * item.product.price for item in cartitems])
            order_value_fee = Decimal(0.05) * Decimal(subtotal)

            # Total delivery fee calculation
            delivery_fee = base_delivery_fee + distance_fee + order_value_fee

            # Add peak hour surcharge
            current_hour = datetime.now().hour
            if 17 <= current_hour <= 20:
                delivery_fee += Decimal(500)

            order.delivery_fee = round(delivery_fee, 2)

            # Save the order
            order.save()

            return order

class UpdateOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order 
        fields = ["pending_status"]

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["id", "name", 'bio', "picture"]


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "id", "phone_number", "street_address", "directions",
            "state", "city", "country", "postal_code"
        ]
        extra_kwargs = {"user": {"required": False}}

    def create(self, validated_data):
        user = self.context["request"].user  # get user from request context
        validated_data["user"] = user

        geolocator = Nominatim(user_agent="ecommerce-app")
        full_address = f"{validated_data.get('street_address', '')}, {validated_data.get('city', '')}, {validated_data.get('country', '')}"
        location = geolocator.geocode(full_address)

        if location:
            validated_data["latitude"] = location.latitude
            validated_data["longitude"] = location.longitude

        return super().create(validated_data)

    def update(self, instance, validated_data):
        geolocator = Nominatim(user_agent="ecommerce-app")
        full_address = f"{validated_data.get('street_address', instance.street_address)}, {validated_data.get('city', instance.city)}, {validated_data.get('country', instance.country)}"
        location = geolocator.geocode(full_address)

        if location:
            validated_data["latitude"] = location.latitude
            validated_data["longitude"] = location.longitude

        return super().update(instance, validated_data)

    
class DeliveryFeeEstimateSerializer(serializers.Serializer):
    address_id = serializers.IntegerField()

    def validate_address_id(self, value):
        try:
            address = Address.objects.get(pk=value)
        except Address.DoesNotExist:
            raise serializers.ValidationError("Address not found.")
        
        if not address.latitude or not address.longitude:
            raise serializers.ValidationError("Address is missing coordinates.")

        return value
    