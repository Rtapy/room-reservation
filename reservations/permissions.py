from rest_framework.permissions import SAFE_METHODS, IsAuthenticated


class IsStaffOrReadOnly(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (
            request.method in SAFE_METHODS or request.user.is_staff
        )


class IsReservationOwnerOrStaff(IsAuthenticated):
    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view) and (
            request.user.is_staff or obj.user_id == request.user.pk
        )
