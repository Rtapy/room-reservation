from django.db.models import Exists, OuterRef

from reservations.models import Reservation, Room


def get_available_rooms(*, start_at, end_at, attendees_count):
    """Return rooms for validated search parameters; this does not reserve them."""
    overlapping = Reservation.objects.filter(
        room_id=OuterRef("pk"),
        status=Reservation.Status.CONFIRMED,
        start_at__lt=end_at,
        end_at__gt=start_at,
    )
    return Room.objects.filter(
        is_active=True, capacity__gte=attendees_count
    ).filter(~Exists(overlapping))
