"""Recorded rides: the trainer page sends the per-second samples once the rider confirms saving.

Open like the read API (no users in phase 1, home network); deleting stays in the admin.
"""

import numpy as np
from rest_framework import mixins, serializers, viewsets

from routes.models import Ride, Route

SERIES = ("t", "dist", "elev", "grade", "sim", "brake", "power", "rpm", "pulse")
# trainer series may contain gaps (null) while the bridge is unreachable; ride series never do
NULLABLE = {"brake", "power", "rpm", "pulse"}
MAX_SAMPLES = 8 * 3600  # one per second: an 8 h ride is plenty


def _clean(values: list) -> np.ndarray:
    return np.array([v for v in values if v is not None], dtype=float)


def summary(s: dict) -> dict:
    """Totals and averages; the cadence and pulse averages ignore standing still and missing readings."""
    dist, elev = np.asarray(s["dist"], float), np.asarray(s["elev"], float)
    power, rpm, pulse = _clean(s["power"]), _clean(s["rpm"]), _clean(s["pulse"])
    rpm, pulse = rpm[rpm > 0], pulse[pulse > 0]

    def stat(fn, a):
        return round(float(fn(a)), 1) if len(a) else None

    return {
        "duration_s": len(s["t"]),
        "distance_m": round(float(np.clip(np.diff(dist), 0, None).sum()), 1),  # seeking back is not riding
        "elev_gain_m": round(float(np.clip(np.diff(elev), 0, None).sum()), 1),
        "avg_power": stat(np.mean, power),
        "max_power": stat(np.max, power),
        "avg_rpm": stat(np.mean, rpm),
        "avg_pulse": stat(np.mean, pulse),
        "max_pulse": stat(np.max, pulse),
    }


SUMMARY_FIELDS = [
    "id",
    "route",
    "title",
    "started_at",
    "duration_s",
    "distance_m",
    "elev_gain_m",
    "avg_power",
    "max_power",
    "avg_rpm",
    "avg_pulse",
    "max_pulse",
]


class RideSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ride
        fields = SUMMARY_FIELDS


class RideDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ride
        fields = [*SUMMARY_FIELDS, "samples"]


class RideCreateSerializer(serializers.ModelSerializer):
    route = serializers.PrimaryKeyRelatedField(queryset=Route.objects.all(), allow_null=True)

    class Meta:
        model = Ride
        fields = ["route", "started_at", "samples"]

    def validate_samples(self, s):
        if not isinstance(s, dict) or set(s) != set(SERIES):
            raise serializers.ValidationError(f"Záznam musí mít řady {', '.join(SERIES)}.")
        n = len(s["t"]) if isinstance(s["t"], list) else -1
        if not 2 <= n <= MAX_SAMPLES:
            raise serializers.ValidationError(f"Záznam musí mít 2 až {MAX_SAMPLES} vzorků.")
        for key, values in s.items():
            ok = isinstance(values, list) and len(values) == n
            ok = ok and all(
                (v is None and key in NULLABLE) or (isinstance(v, int | float) and not isinstance(v, bool))
                for v in values
            )
            if not ok:
                raise serializers.ValidationError(f"Řada {key}: {n} čísel" + (" nebo null" if key in NULLABLE else ""))
        return s

    def create(self, data):
        route = data["route"]
        return Ride.objects.create(
            route=route,
            title=route.title if route else "Jízda",
            started_at=data["started_at"],
            samples=data["samples"],
            **summary(data["samples"]),
        )

    def to_representation(self, instance):
        return RideSerializer(instance).data


class RideViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Ride.objects.all()

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.defer("samples") if self.action == "list" else qs

    def get_serializer_class(self):
        return {"create": RideCreateSerializer, "list": RideSerializer}.get(self.action, RideDetailSerializer)
