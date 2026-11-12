import io

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from PIL import Image, ImageOps

from .models import DEPARTMENTS, YEARS, Comment, Level, Message, Listing, Profile, Rating, TradeRequest, Wanted


class SignupForm(UserCreationForm):
    level = forms.ChoiceField(choices=Level.choices)
    department = forms.ChoiceField(choices=DEPARTMENTS)
    year = forms.ChoiceField(choices=YEARS)
    is_alumni = forms.BooleanField(required=False, label="I have already passed out")

    class Meta:
        model = User
        fields = ("username", "email")

    def save_profile(self, user):
        d = self.cleaned_data
        return Profile.objects.create(user=user, level=d["level"], department=d["department"],
                                      year=d["year"], is_alumni=d["is_alumni"])


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["level", "department", "year", "is_alumni", "bio"]


def make_thumb(upload):
    """Shrink an uploaded photo to a small JPEG so it is cheap to store and serve."""
    im = ImageOps.exif_transpose(Image.open(upload)).convert("RGB")
    im.thumbnail((640, 640))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=78, optimize=True)
    return buf.getvalue()


class ListingForm(forms.ModelForm):
    photo = forms.ImageField(required=False, label="Cover photo (optional)")
    remove_photo = forms.BooleanField(required=False, label="Remove current photo")

    class Meta:
        model = Listing
        fields = ["title", "kind", "offer", "level", "department", "year", "semester",
                  "course_code", "edition", "condition", "pickup", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            del self.fields["remove_photo"]

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Photo must be under 5 MB.")
        return photo

    def save(self, commit=True):
        obj = super().save(commit=False)
        photo = self.cleaned_data.get("photo")
        if photo:
            obj.thumb, obj.has_photo = make_thumb(photo), True
        elif self.cleaned_data.get("remove_photo"):
            obj.thumb, obj.has_photo = None, False
        if commit:
            obj.save()
        return obj


class TradeRequestForm(forms.ModelForm):
    class Meta:
        model = TradeRequest
        fields = ["offered", "message"]  # kind is copied from the listing's offer

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offered"].queryset = Listing.objects.filter(owner=user, is_available=True)
        self.fields["offered"].required = False
        self.fields["offered"].label = "Your item to swap (trades only)"


class RatingForm(forms.ModelForm):
    class Meta:
        model = Rating
        fields = ["score", "comment"]


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["text"]
        labels = {"text": "Ask a question or leave a comment"}
        widgets = {"text": forms.Textarea(attrs={"rows": 2})}


class WantedForm(forms.ModelForm):
    class Meta:
        model = Wanted
        fields = ["title", "course_code", "level", "department", "year", "note"]


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["text"]
        labels = {"text": "Message"}
        widgets = {"text": forms.Textarea(attrs={"rows": 2})}
