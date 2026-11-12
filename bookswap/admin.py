from django.contrib import admin
from .models import (Comment, Listing, Message, Notification, Profile, Rating, Reaction, Report, Saved,
                     TradeRequest, Wanted)

for m in (Profile, Listing, TradeRequest, Rating, Reaction, Saved, Comment, Notification, Wanted, Report, Message):
    admin.site.register(m)
