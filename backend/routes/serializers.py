from rest_framework import serializers

from routes.models import Route, Video


class VideoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Video
        fields = ["source", "source_id", "duration_s"]


class VideoDetailSerializer(VideoSerializer):
    class Meta(VideoSerializer.Meta):
        fields = [*VideoSerializer.Meta.fields, "timing"]


class RouteSerializer(serializers.ModelSerializer):
    video = VideoSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Route
        fields = ["id", "title", "distance_km", "elev_gain_m", "elev_loss_m", "max_grade", "video"]


class RouteDetailSerializer(RouteSerializer):
    video = VideoDetailSerializer(read_only=True, allow_null=True)

    class Meta(RouteSerializer.Meta):
        fields = [*RouteSerializer.Meta.fields, "segment", "profile"]
