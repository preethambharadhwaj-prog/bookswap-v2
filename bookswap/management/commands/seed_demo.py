from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from bookswap.models import Comment, Listing, Profile, Rating, Reaction, TradeRequest, Wanted

PASSWORD = "demo12345"
USERS = [  # username, level, department, year, alumni
    ("arjun_s", "btech", "CSE", 4, False), ("meera_k", "btech", "CSE", 2, False),
    ("kiran_r", "poly", "EEE", 1, False), ("divya_m", "btech", "ECE", 3, False),
    ("sandeep_p", "btech", "ME", 2, False), ("anita_v", "mtech", "CSE", 2, False),
    ("rahul_alumni", "btech", "CSE", 4, True),
]
LISTINGS = [  # owner, title, kind, offer, level, dept, year, sem, code, edition, cond, pickup
    ("arjun_s", "Engineering Mathematics I", "book", "donate", "btech", "CSE", 1, 1, "MA101", "3rd", "good", "Hostel C reception, 6 pm"),
    ("arjun_s", "Data Structures notes", "notes", "lend", "btech", "CSE", 2, 3, "CS201", "", "new", "Library gate"),
    ("meera_k", "Engineering Physics", "book", "donate", "btech", "CSE", 1, 2, "PH102", "2nd", "fair", "Canteen"),
    ("meera_k", "C Programming handwritten notes", "notes", "donate", "btech", "CSE", 1, 1, "CS101", "", "good", "CSE block lobby"),
    ("kiran_r", "Basic Electrical Engineering", "book", "trade", "poly", "EEE", 1, 1, "EE101", "1st", "good", "Workshop gate"),
    ("divya_m", "Digital Logic Design", "book", "lend", "btech", "ECE", 2, 3, "EC203", "5th", "good", "ECE dept office"),
    ("divya_m", "Signals & Systems notes", "notes", "donate", "btech", "ECE", 2, 4, "EC204", "", "new", "Library"),
    ("sandeep_p", "Thermodynamics", "book", "lend", "btech", "ME", 2, 3, "ME203", "4th", "worn", "Hostel A"),
    ("anita_v", "Advanced Algorithms", "book", "donate", "mtech", "CSE", 1, 1, "CS601", "2nd", "good", "PG block"),
    ("rahul_alumni", "Operating Systems (Galvin)", "book", "donate", "btech", "CSE", 3, 5, "CS305", "9th", "good", "Shipped via seniors"),
    ("rahul_alumni", "DBMS notes", "notes", "donate", "btech", "CSE", 3, 5, "CS306", "", "good", "Library"),
    ("arjun_s", "Engineering Chemistry", "book", "donate", "btech", "CSE", 1, 2, "CY101", "3rd", "good", "Hostel C reception"),
]


class Command(BaseCommand):
    help = "Create demo users, listings, reactions, a completed exchange and wanted posts."

    def handle(self, *args, **opts):
        if User.objects.filter(username="arjun_s").exists():
            self.stdout.write("Demo data already exists, nothing to do.")
            return
        users = {}
        for name, level, dept, year, alumni in USERS:
            u = User.objects.create_user(name, password=PASSWORD)
            Profile.objects.create(user=u, level=level, department=dept, year=year, is_alumni=alumni)
            users[name] = u
        made = []
        for o, title, kind, offer, level, dept, year, sem, code, ed, cond, pickup in LISTINGS:
            made.append(Listing.objects.create(
                owner=users[o], title=title, kind=kind, offer=offer, level=level, department=dept,
                year=year, semester=sem, course_code=code, edition=ed, condition=cond, pickup=pickup,
                description="Pass-down from a senior. Message me to arrange a pickup."))
        names = list(users)
        for i, l in enumerate(made):  # a few reactions each
            for j, key in enumerate(("like", "love", "fire", "thanks")[: 1 + i % 4]):
                voter = users[names[(i + j + 1) % len(names)]]
                if voter != l.owner:
                    Reaction.objects.get_or_create(listing=l, user=voter, emoji=key)
        Comment.objects.create(listing=made[0], author=users["meera_k"], text="Is the 3rd edition still available?")
        Comment.objects.create(listing=made[0], author=users["arjun_s"], text="Yes! Pickup works any evening.")
        # one finished exchange with ratings so the community page has data
        tr = TradeRequest.objects.create(listing=made[9], requester=users["meera_k"], kind="donate", status="done")
        made[9].is_available = False
        made[9].save(update_fields=["is_available"])
        Rating.objects.create(trade=tr, rater=users["meera_k"], ratee=users["rahul_alumni"], score=5, comment="Smooth handover")
        Rating.objects.create(trade=tr, rater=users["rahul_alumni"], ratee=users["meera_k"], score=5, comment="On time")
        Wanted.objects.create(user=users["kiran_r"], title="Digital Electronics notes", course_code="EC110", level="poly", department="EEE", year=1)
        Wanted.objects.create(user=users["divya_m"], title="Control Systems textbook", course_code="EC305", level="btech", department="ECE", year=3, note="Any edition")
        self.stdout.write(self.style.SUCCESS(f"Created {len(users)} users and {len(made)} listings. Password for all: {PASSWORD}"))
