from flask_wtf import FlaskForm
from wtforms import BooleanField, FileField, HiddenField, IntegerField, PasswordField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, NumberRange, Optional


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    submit = SubmitField("Sign in")


class CheckoutForm(FlaskForm):
    customer_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    customer_phone = StringField("Phone number", validators=[DataRequired(), Length(min=7, max=30)])
    customer_email = StringField("Email address", validators=[Optional(), Email(), Length(max=254)])
    fulfillment = SelectField("Fulfillment", choices=[("pickup", "Pickup"), ("delivery", "Delivery")], validators=[DataRequired()])
    delivery_address = StringField("Delivery address", validators=[Optional(), Length(max=500)])
    delivery_zone = SelectField("Delivery area", choices=[], validators=[Optional()])
    delivery_instructions = TextAreaField("Delivery instructions", validators=[Optional(), Length(max=500)])
    pickup_name = StringField("Name for pickup", validators=[Optional(), Length(max=120)])
    order_notes = TextAreaField("Order notes", validators=[Optional(), Length(max=1000)])
    payment_method = HiddenField(default="bank_transfer", validators=[DataRequired()])
    terms_acknowledged = BooleanField("I agree to the order terms", validators=[InputRequired(message="Please acknowledge the order terms.")])
    submit = SubmitField("Place order")

    def validate(self, extra_validators=None):
        valid = super().validate(extra_validators=extra_validators)
        if self.fulfillment.data == "pickup" and not (self.pickup_name.data or "").strip():
            self.pickup_name.errors.append("Enter the name the order will be collected under.")
            valid = False
        if self.fulfillment.data == "delivery":
            if not (self.delivery_zone.data or "").strip():
                self.delivery_zone.errors.append("Choose a delivery area.")
                valid = False
            if len((self.delivery_address.data or "").strip()) < 5:
                self.delivery_address.errors.append("Enter a complete delivery address.")
                valid = False
        return valid


class CustomerRegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=254)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    submit = SubmitField("Create account")


class ProductForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=140)])
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    image_url = StringField("Image URL", validators=[Optional(), Length(max=500)])
    image_alt = StringField("Image alt text", validators=[Optional(), Length(max=180)])
    image_file = FileField("Upload product image")
    small_price = StringField("Small price (R)", validators=[Optional(), Length(max=15)])
    medium_price = StringField("Medium price (R)", validators=[Optional(), Length(max=15)])
    regular_price = StringField("Regular price (R)", validators=[Optional(), Length(max=15)])
    active = BooleanField("Published")
    available = BooleanField("Available")
    featured = BooleanField("Featured")
    stock_quantity = IntegerField("Stock quantity (blank = not tracked)", validators=[Optional(), NumberRange(min=0, max=1000000)])
    confirm_review = BooleanField("I confirm the product name and prices are correct")
    submit = SubmitField("Save product")


class SettingsForm(FlaskForm):
    business_name = StringField("Business name", validators=[DataRequired(), Length(max=120)])
    outlet_address = StringField("Outlet address", validators=[Length(max=500)])
    contact_phone = StringField("Contact phone", validators=[Length(max=30)])
    contact_email = StringField("Contact email", validators=[Optional(), Email(), Length(max=254)])
    bank_name = StringField("Bank name", validators=[Optional(), Length(max=120)])
    bank_account_name = StringField("Account holder", validators=[Optional(), Length(max=120)])
    bank_account_number = StringField("Account number", validators=[Optional(), Length(max=40)])
    bank_branch_code = StringField("Branch code", validators=[Optional(), Length(max=20)])
    bank_account_type = StringField("Account type", validators=[Optional(), Length(max=40)])
    opening_hours = StringField("Opening hours", validators=[Length(max=500)])
    delivery_zones = TextAreaField("Delivery zones (one per line)", validators=[Length(max=1000)])
    delivery_fee = StringField("Delivery fee (R)", validators=[Length(max=15)])
    pickup_prep_minutes = StringField("Pickup preparation estimate (minutes)", validators=[Optional(), Length(max=6)])
    delivery_estimate_minutes = StringField("Delivery estimate (minutes)", validators=[Optional(), Length(max=6)])
    promo_banner = StringField("Homepage promotional banner", validators=[Optional(), Length(max=300)])
    minimum_order = StringField("Minimum order (R)", validators=[Optional(), Length(max=15)])
    tax_rate = StringField("Tax rate (%)", validators=[Length(max=8)])
    pickup_enabled = BooleanField("Pickup enabled")
    delivery_enabled = BooleanField("Delivery enabled")
    maintenance_mode = BooleanField("Maintenance mode")
    submit = SubmitField("Save settings")


class StatusForm(FlaskForm):
    status = SelectField("New status", choices=[], validators=[DataRequired()])
    reason = StringField("Reason", validators=[Optional(), Length(max=500)])
    submit = SubmitField("Update order")


class CollectPaymentForm(FlaskForm):
    amount = StringField("Amount collected (R)", validators=[DataRequired(), Length(max=15)])
    method = SelectField("Collection method", choices=[("cash", "Cash"), ("card", "Card at outlet"), ("eft", "EFT")], validators=[DataRequired()])
    submit = SubmitField("Record payment")