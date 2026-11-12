import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .models import (Comment, Listing, Message, Notification, Profile, Rating, Reaction, Saved,
                     TradeRequest, Wanted)

PW = "pw12345!xyz"


def make_user(name, level="btech", dept="CSE", year=1):
    u = User.objects.create_user(name, password=PW)
    Profile.objects.create(user=u, level=level, department=dept, year=year)
    return u


def make_listing(owner, **kw):
    data = dict(title="Maths I", kind="book", offer="donate", level="btech", department="CSE",
                year=1, semester=1, course_code="MA101", condition="good")
    data.update(kw)
    return Listing.objects.create(owner=owner, **data)


class BookSwapTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner", year=2)
        self.req = make_user("req")
        self.other = make_user("other")
        self.listing = make_listing(self.owner)

    def login(self, user):
        self.client.login(username=user.username, password=PW)

    def make_trade(self, status="pending"):
        return TradeRequest.objects.create(listing=self.listing, requester=self.req,
                                           kind="donate", status=status)

    # ---- public pages
    def test_browse_is_public_and_shows_listing(self):
        r = self.client.get(reverse("listing_list"))
        self.assertContains(r, "Maths I")

    def test_bad_filters_do_not_crash(self):
        r = self.client.get("/?year=abc&semester=x&sort=zzz&page=999")
        self.assertEqual(r.status_code, 200)

    def test_signup_creates_profile(self):
        r = self.client.post(reverse("signup"), {
            "username": "newbie", "email": "n@x.com", "password1": PW, "password2": PW,
            "level": "btech", "department": "CSE", "year": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Profile.objects.filter(user__username="newbie").exists())

    # ---- listings and photos
    def test_create_listing_with_photo(self):
        self.login(self.owner)
        buf = io.BytesIO()
        Image.new("RGB", (900, 600), "red").save(buf, "PNG")
        photo = SimpleUploadedFile("c.png", buf.getvalue(), content_type="image/png")
        r = self.client.post(reverse("listing_create"), {
            "title": "Physics", "kind": "book", "offer": "lend", "level": "btech",
            "department": "CSE", "year": "1", "semester": "2", "course_code": "PH102",
            "edition": "2", "condition": "good", "pickup": "Library", "description": "", "photo": photo})
        self.assertEqual(r.status_code, 302)
        l = Listing.objects.get(title="Physics")
        self.assertTrue(l.has_photo)
        img = self.client.get(reverse("listing_image", args=[l.pk]))
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img["Content-Type"], "image/jpeg")

    def test_only_owner_can_edit_or_delete(self):
        self.login(self.req)
        self.assertEqual(self.client.get(reverse("listing_edit", args=[self.listing.pk])).status_code, 404)
        self.client.post(reverse("listing_delete", args=[self.listing.pk]))
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    # ---- request flow
    def test_full_request_flow(self):
        self.login(self.req)
        self.client.post(reverse("request_create", args=[self.listing.pk]), {"message": "hi"})
        tr = TradeRequest.objects.get()
        self.assertEqual(tr.status, "pending")
        self.assertTrue(Notification.objects.filter(user=self.owner).exists())

        self.login(self.owner)
        self.client.post(reverse("request_update", args=[tr.pk, "accept"]))
        tr.refresh_from_db(); self.listing.refresh_from_db()
        self.assertEqual(tr.status, "accepted")
        self.assertFalse(self.listing.is_available)
        self.client.post(reverse("request_update", args=[tr.pk, "done"]))
        tr.refresh_from_db()
        self.assertEqual(tr.status, "done")

        self.login(self.req)
        self.client.post(reverse("rate", args=[tr.pk]), {"score": 5, "comment": "great"})
        self.assertEqual(Rating.objects.get().ratee, self.owner)
        self.assertEqual(self.owner.profile.avg_rating, 5)

    def test_cannot_request_own_listing(self):
        self.login(self.owner)
        r = self.client.post(reverse("request_create", args=[self.listing.pk]), {"message": "x"})
        self.assertEqual(r.status_code, 403)

    def test_requester_cannot_accept(self):
        tr = self.make_trade()
        self.login(self.req)
        r = self.client.post(reverse("request_update", args=[tr.pk, "accept"]))
        self.assertEqual(r.status_code, 404)

    # ---- reactions, saved, comments
    def test_reaction_and_save_toggle(self):
        self.login(self.req)
        url = reverse("react", args=[self.listing.pk, "like"])
        self.client.post(url)
        self.assertEqual(Reaction.objects.count(), 1)
        self.client.post(url)
        self.assertEqual(Reaction.objects.count(), 0)
        self.client.post(reverse("listing_save", args=[self.listing.pk]))
        self.assertEqual(Saved.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("saved_list")).status_code, 200)

    def test_comment_notifies_owner(self):
        self.login(self.req)
        self.client.post(reverse("comment_create", args=[self.listing.pk]), {"text": "Still available?"})
        self.assertEqual(Comment.objects.count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.owner, text__contains="commented").exists())

    # ---- moderation, wanted, chat
    def test_three_reports_hide_listing(self):
        extra = make_user("extra")
        for u in (self.req, self.other, extra):
            self.login(u)
            self.client.post(reverse("report", args=[self.listing.pk]))
        self.listing.refresh_from_db()
        self.assertFalse(self.listing.is_available)

    def test_wanted_match_notifies_poster(self):
        Wanted.objects.create(user=self.req, title="Maths book", course_code="MA101")
        self.login(self.owner)
        self.client.post(reverse("listing_create"), {
            "title": "Maths II", "kind": "book", "offer": "donate", "level": "btech",
            "department": "CSE", "year": "1", "semester": "2", "course_code": "ma101",
            "edition": "", "condition": "good", "pickup": "", "description": ""})
        self.assertTrue(Notification.objects.filter(user=self.req, text__contains="MA101").exists())

    def test_chat_access_and_notification(self):
        tr = self.make_trade("accepted")
        self.login(self.other)
        self.assertEqual(self.client.get(reverse("request_chat", args=[tr.pk])).status_code, 403)
        self.login(self.req)
        self.client.post(reverse("request_chat", args=[tr.pk]), {"text": "Meet at 5?"})
        self.assertEqual(Message.objects.count(), 1)
        self.assertTrue(Notification.objects.filter(user=self.owner, text__contains="message").exists())

    def test_other_pages_render(self):
        self.login(self.req)
        for name in ("listing_list", "wanted_list", "wanted_create", "notifications", "community",
                     "my_listings", "saved_list", "my_requests", "profile_edit", "listing_create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("listing_detail", args=[self.listing.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("profile", args=["owner"])).status_code, 200)
