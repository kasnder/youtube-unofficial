from typing import Any, Dict, Sequence

from typing_extensions import TypedDict

from youtube_unofficial.typing.browse_ajax import NextContinuationDict

__all__ = ('PlaylistInfo', )


class WatchEndpointDict(TypedDict):
    videoId: str


class NavigationEndpointDict(TypedDict):
    watchEndpoint: WatchEndpointDict


class HasKeyText(TypedDict):
    text: str


class RunsOrSimpleTextDict(TypedDict, total=False):
    runs: Sequence[HasKeyText]
    simpleText: str


class RunsOrTextDict(TypedDict, total=False):
    runs: Sequence[HasKeyText]
    text: str


class PlaylistVideoRendererDict(TypedDict, total=False):
    navigationEndpoint: NavigationEndpointDict
    shortBylineText: RunsOrTextDict
    title: RunsOrSimpleTextDict
    videoId: str


class PlaylistInfo(TypedDict, total=False):
    continuationItemRenderer: Dict[str, Any]
    playlistVideoRenderer: PlaylistVideoRendererDict


class PlaylistVideoListRendererContinuationsDict(TypedDict):
    nextContinuationData: NextContinuationDict


class PlaylistVideoListRenderer(TypedDict):
    contents: Sequence[PlaylistInfo]
    continuations: Sequence[PlaylistVideoListRendererContinuationsDict]
