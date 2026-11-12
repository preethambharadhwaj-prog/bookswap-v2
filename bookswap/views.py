from collections import defaultdict
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (CommentForm, ListingForm, MessageForm, ProfileForm, RatingForm, SignupForm,
                    TradeRequestForm, WantedForm)
from .models import (DEPARTMENTS, REACTIONS, SEMESTERS, YEARS, Comment, Level, Listing, Notification,
                     Profile, Reaction, Report, Saved, TradeRequest, Wanted)

EMOJI = dict(REACTIONS)
SORTS = [("new", "Newest"), ("old", "Oldest"), ("title", "Title A-Z")]
ORDER = {"new": "-created", "old": "created", "title": "title"}
EXACT = ("level", "department", "year", "semester", "condition", "kind", "offer")
NUMERIC = ("year", "semester")
TEXT = ("course_code", "edition")
PAGE_SIZE = 12
REPORT_LIMIT = 3


def notify(user, text, url=""):
    Notification.objects.create(user=user, text=text[:200], url=url)


def cards(qs, user):
    """Evaluate a listing queryset and attach reaction counts + saved flag (3 queries total)."""
    listings = list(qs)
    ids = [l.pk for l in listings]
    counts = defaultdict(dict)
    for r in (Reaction.objects.filter(listing_id__in=ids)
              .values("listing_id", "emoji").annotate(n=Count("id"))):
        counts[r["listing_id"]][r["emoji"]] = r["n"]
    mine, saved = set(), set()
    if user.is_authenticated:
        mine = set(Reaction.objects.filter(listing_id__in=ids, user=user)
                   .values_list("listing_id", "emoji"))
        saved = set(Saved.objects.filter(user=user, listing_id__in=ids)
                    .values_list("listing_id", flat=True))
    for l in listings:
        l.reacts = [{"key": k, "char": c, "n": counts[l.pk].get(k, 0), "mine": (l.pk, k) in mine}
                    for k, c in REACTIONS]
        l.is_saved = l.pk in saved
    return listings


def back(request, pk):
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return nxt
    return reverse("listing_detail", args=[pk])


def signup(request):
    form = SignupForm(request.POST or None)
    if form.is_valid():
        user = form.save()
        form.save_profile(user)
        login(request, user)
        return redirect("listing_list")
    return render(request, "registration/signup.html", {"form": form})


def listing_list(request):
    g = request.GET.dict()
    # first visit: default to what this student needs (their own level/dept/year)
    if not g and request.user.is_authenticated and hasattr(request.user, "profile"):
        p = request.user.profile
        g = {"level": p.level, "department": p.department, "year": str(p.year or "")}
    qs = Listing.objects.filter(is_available=True).select_related("owner__profile").defer("thumb")
    if g.get("q"):
        qs = qs.filter(Q(title__icontains=g["q"]) | Q(description__icontains=g["q"]))
    for f in EXACT:
        v = g.get(f)
        if v and not (f in NUMERIC and not v.isdigit()):
            qs = qs.filter(**{f: v})
    for f in TEXT:
        if g.get(f):
            qs = qs.filter(**{f"{f}__iexact": g[f]})
    qs = qs.order_by(ORDER.get(g.get("sort"), "-created"))
    page = Paginator(qs, PAGE_SIZE).get_page(g.get("page"))
    qs_str = urlencode({k: val for k, val in g.items() if val and k != "page"})
    return render(request, "bookswap/listing_list.html", {
        "listings": cards(page.object_list, request.user), "page": page, "qs_str": qs_str, "g": g, "levels": Level.choices,
        "departments": DEPARTMENTS, "years": YEARS, "semesters": SEMESTERS,
        "conditions": Listing.Condition.choices, "kinds": Listing.Kind.choices,
        "offers": Listing.Offer.choices, "sorts": SORTS})


def listing_detail(request, pk):
    qs = Listing.objects.filter(pk=pk).select_related("owner__profile").defer("thumb")
    if not qs.exists():
        raise Http404
    listing = cards(qs, request.user)[0]
    authed = request.user.is_authenticated
    return render(request, "bookswap/listing_detail.html", {
        "listing": listing, "form": TradeRequestForm(user=request.user) if authed else None,
        "comments": Comment.objects.filter(listing=listing).select_related("author"),
        "comment_form": CommentForm(),
        "reported": authed and Report.objects.filter(listing=listing, reporter=request.user).exists()})


def listing_image(request, pk):
    l = get_object_or_404(Listing.objects.only("thumb"), pk=pk, has_photo=True)
    resp = HttpResponse(bytes(l.thumb), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=300"
    return resp


@login_required
def listing_create(request):
    form = ListingForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        listing = form.save(commit=False)
        listing.owner = request.user
        listing.save()
        if listing.course_code:  # tell students who asked for this course's material
            for w in (Wanted.objects.filter(is_open=True, course_code__iexact=listing.course_code)
                      .exclude(user=request.user).select_related("user")):
                notify(w.user, f"A listing for {listing.course_code} just appeared: {listing.title}",
                       reverse("listing_detail", args=[listing.pk]))
        messages.success(request, "Listing published.")
        return redirect("listing_detail", pk=listing.pk)
    return render(request, "bookswap/listing_form.html", {"form": form, "title": "New listing"})


@login_required
def listing_edit(request, pk):
    listing = get_object_or_404(Listing, pk=pk, owner=request.user)
    form = ListingForm(request.POST or None, request.FILES or None, instance=listing)
    if form.is_valid():
        form.save()
        return redirect("listing_detail", pk=listing.pk)
    return render(request, "bookswap/listing_form.html", {"form": form, "title": "Edit listing"})


@login_required
@require_POST
def listing_delete(request, pk):
    get_object_or_404(Listing.objects.only("id"), pk=pk, owner=request.user).delete()
    return redirect("my_listings")


@login_required
@require_POST
def listing_toggle(request, pk):
    l = get_object_or_404(Listing.objects.defer("thumb"), pk=pk, owner=request.user)
    l.is_available = not l.is_available
    l.save(update_fields=["is_available"])
    return redirect("my_listings")


@login_required
@require_POST
def listing_save(request, pk):
    listing = get_object_or_404(Listing.objects.only("id"), pk=pk)
    obj, created = Saved.objects.get_or_create(user=request.user, listing=listing)
    if not created:
        obj.delete()
    return redirect(back(request, pk))


@login_required
@require_POST
def react(request, pk, key):
    if key not in EMOJI:
        raise Http404
    listing = get_object_or_404(Listing.objects.only("id"), pk=pk)
    obj, created = Reaction.objects.get_or_create(listing=listing, user=request.user, emoji=key)
    if not created:
        obj.delete()
    return redirect(back(request, pk))


@login_required
def my_listings(request):
    qs = Listing.objects.filter(owner=request.user).select_related("owner__profile").defer("thumb")
    return render(request, "bookswap/my_listings.html", {"listings": cards(qs, request.user)})


@login_required
def saved_list(request):
    ids = Saved.objects.filter(user=request.user).values_list("listing_id", flat=True)
    qs = Listing.objects.filter(pk__in=ids).select_related("owner__profile").defer("thumb")
    return render(request, "bookswap/saved.html", {"listings": cards(qs, request.user)})


@login_required
@require_POST
def request_create(request, pk):
    listing = get_object_or_404(Listing.objects.defer("thumb"), pk=pk, is_available=True)
    if listing.owner == request.user:
        return HttpResponseForbidden("This is your own listing.")
    form = TradeRequestForm(request.POST, user=request.user)
    if form.is_valid():
        tr = form.save(commit=False)
        tr.listing, tr.requester, tr.kind = listing, request.user, listing.offer
        tr.save()
        notify(listing.owner, f"{request.user.username} requested “{listing.title}”", reverse("my_requests"))
        messages.success(request, "Request sent. You'll get a notification when the owner replies.")
    return redirect("my_requests")


def requests_qs():
    return (TradeRequest.objects.select_related("listing__owner", "requester", "offered")
            .defer("listing__thumb", "offered__thumb"))


@login_required
def my_requests(request):
    return render(request, "bookswap/my_requests.html", {
        "incoming": requests_qs().filter(listing__owner=request.user),
        "outgoing": requests_qs().filter(requester=request.user),
    })


@login_required
@require_POST
def request_update(request, pk, action):
    tr = get_object_or_404(requests_qs(), pk=pk, listing__owner=request.user)
    if action == "accept":
        tr.status = "accepted"
        tr.listing.is_available = False  # hide from search while deal is on
        tr.listing.save(update_fields=["is_available"])
        notify(tr.requester, f"Your request for “{tr.listing.title}” was accepted", reverse("my_requests"))
    elif action == "decline":
        tr.status = "declined"
        notify(tr.requester, f"Your request for “{tr.listing.title}” was declined", reverse("my_requests"))
    elif action == "done" and tr.status == "accepted":
        tr.status = "done"
        notify(tr.requester, f"“{tr.listing.title}” is marked completed. Please rate {request.user.username}",
               reverse("rate", args=[tr.pk]))
    tr.save()
    return redirect("my_requests")


@login_required
def rate(request, pk):
    tr = get_object_or_404(requests_qs(), pk=pk, status="done")
    if request.user not in (tr.requester, tr.owner):
        return HttpResponseForbidden()
    ratee = tr.owner if request.user == tr.requester else tr.requester
    form = RatingForm(request.POST or None)
    if form.is_valid() and not tr.ratings.filter(rater=request.user).exists():
        r = form.save(commit=False)
        r.trade, r.rater, r.ratee = tr, request.user, ratee
        r.save()
        notify(ratee, f"{request.user.username} rated you {r.score}/5", reverse("profile", args=[ratee.username]))
        return redirect("profile", username=ratee.username)
    return render(request, "bookswap/rating_form.html", {"form": form, "ratee": ratee})


def profile(request, username):
    user = get_object_or_404(User, username=username)
    prof, _ = Profile.objects.get_or_create(user=user)
    qs = Listing.objects.filter(owner=user, is_available=True).select_related("owner__profile").defer("thumb")
    return render(request, "bookswap/profile.html", {
        "u": user, "prof": prof, "listings": cards(qs, request.user),
        "ratings": user.ratings_received.select_related("rater"),
    })


@login_required
def profile_edit(request):
    prof, _ = Profile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, instance=prof)
    if form.is_valid():
        form.save()
        return redirect("profile", username=request.user.username)
    return render(request, "bookswap/listing_form.html", {"form": form, "title": "Edit profile"})


@login_required
@require_POST
def comment_create(request, pk):
    listing = get_object_or_404(Listing.objects.defer("thumb").select_related("owner"), pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        c = form.save(commit=False)
        c.listing, c.author = listing, request.user
        c.save()
        if listing.owner != request.user:
            notify(listing.owner, f"{request.user.username} commented on “{listing.title}”",
                   reverse("listing_detail", args=[pk]))
    return redirect("listing_detail", pk=pk)


@login_required
@require_POST
def comment_delete(request, pk):
    c = get_object_or_404(Comment.objects.select_related("listing__owner").defer("listing__thumb"), pk=pk)
    if request.user in (c.author, c.listing.owner):
        c.delete()
    return redirect("listing_detail", pk=c.listing_id)


@login_required
@require_POST
def report(request, pk):
    listing = get_object_or_404(Listing.objects.defer("thumb").select_related("owner"), pk=pk)
    if listing.owner != request.user:
        _, created = Report.objects.get_or_create(
            listing=listing, reporter=request.user,
            defaults={"reason": request.POST.get("reason", "")[:200]})
        messages.success(request, "Thanks, your report was recorded.")
        if created and listing.is_available and listing.reports.count() >= REPORT_LIMIT:
            listing.is_available = False
            listing.save(update_fields=["is_available"])
            notify(listing.owner, f"“{listing.title}” was hidden after several reports. You can re-show it in My items.",
                   reverse("my_listings"))
    return redirect("listing_detail", pk=pk)


def wanted_list(request):
    qs = Wanted.objects.filter(is_open=True).select_related("user")
    q = request.GET.get("q", "")
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(course_code__icontains=q))
    return render(request, "bookswap/wanted_list.html", {"items": qs, "q": q})


@login_required
def wanted_create(request):
    form = WantedForm(request.POST or None)
    if form.is_valid():
        w = form.save(commit=False)
        w.user = request.user
        w.save()
        messages.success(request, "Posted. Seniors and alumni can now offer you this.")
        return redirect("wanted_list")
    return render(request, "bookswap/listing_form.html", {"form": form, "title": "What do you need?"})


@login_required
@require_POST
def wanted_offer(request, pk):
    w = get_object_or_404(Wanted.objects.select_related("user"), pk=pk, is_open=True)
    if w.user != request.user:
        notify(w.user, f"{request.user.username} may have “{w.title}”. See their items.",
               reverse("profile", args=[request.user.username]))
        messages.success(request, "Sent! They have been notified.")
    return redirect("wanted_list")


@login_required
@require_POST
def wanted_close(request, pk):
    w = get_object_or_404(Wanted, pk=pk, user=request.user)
    w.is_open = False
    w.save(update_fields=["is_open"])
    return redirect("wanted_list")


@login_required
def notifications(request):
    items = list(Notification.objects.filter(user=request.user)[:50])
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return render(request, "bookswap/notifications.html", {"items": items})


def community(request):
    donors = (User.objects.annotate(n=Count("listings__requests", filter=Q(listings__requests__status="done"), distinct=True))
              .filter(n__gt=0).order_by("-n")[:10])
    rated = (User.objects.annotate(avg=Avg("ratings_received__score"), cnt=Count("ratings_received", distinct=True))
             .filter(cnt__gte=1).order_by("-avg", "-cnt")[:5])
    stats = {"members": User.objects.count(), "listings": Listing.objects.count(),
             "done": TradeRequest.objects.filter(status="done").count(),
             "wanted": Wanted.objects.filter(is_open=True).count()}
    return render(request, "bookswap/community.html", {"donors": donors, "rated": rated, "stats": stats})


@login_required
def request_chat(request, pk):
    tr = get_object_or_404(requests_qs(), pk=pk)
    if request.user not in (tr.requester, tr.owner):
        return HttpResponseForbidden()
    other = tr.owner if request.user == tr.requester else tr.requester
    form = MessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        msg = form.save(commit=False)
        msg.trade, msg.sender = tr, request.user
        msg.save()
        notify(other, f"New message from {request.user.username} about “{tr.listing.title}”",
               reverse("request_chat", args=[pk]))
        return redirect("request_chat", pk=pk)
    return render(request, "bookswap/chat.html", {
        "tr": tr, "other": other, "thread": tr.messages.select_related("sender"), "form": form})
