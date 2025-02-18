from datetime import datetime
from http.cookiejar import CookieJar, LoadError, MozillaCookieJar
from os.path import expanduser
from time import sleep
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Type, cast
import hashlib
import json
import logging

from requests.exceptions import HTTPError
from typing_extensions import Final
import requests

from .community import CommunityHistoryEntry, make_community_history_entry
from .constants import (BROWSE_AJAX_URL, COMMUNITY_HISTORY_URL, HISTORY_URL,
                        SEARCH_HISTORY_URL, SERVICE_AJAX_URL, USER_AGENT,
                        WATCH_HISTORY_URL, WATCH_LATER_URL)
from .download import DownloadMixin
from .exceptions import AuthenticationError, UnexpectedError
from .initial import initial_data
from .login import YouTubeLogin
from .typing import HasStringCode
from .typing.browse_ajax import BrowseAJAXSequence
from .typing.playlist import PlaylistInfo, PlaylistVideoListRenderer
from .typing.ytcfg import YtcfgDict
from .util import context_client_body, path as at_path, path_default
from .ytcfg import find_ytcfg, ytcfg_headers

__all__ = ('YouTube', )


class YouTube(DownloadMixin):
    def __init__(self,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 netrc_file: Optional[str] = None,
                 cookies_path: Optional[str] = None,
                 logged_in: bool = False,
                 cookiejar_cls: Type[CookieJar] = MozillaCookieJar):
        if not netrc_file:
            self.netrc_file = expanduser('~/.netrc')
        else:
            self.netrc_file = netrc_file
        if not cookies_path:
            cookies_path = expanduser('~/.local/share/cookies/youtube.txt')
        self.username = username
        self.password = password
        self._log: Final[logging.Logger] = logging.getLogger(
            'youtube-unofficial')
        self._sess = requests.Session()
        self._init_cookiejar(cookies_path, cls=cookiejar_cls)
        self._sess.cookies = self._cj  # type: ignore[assignment]
        self._sess.headers.update({'User-Agent': USER_AGENT})
        self._login_handler = YouTubeLogin(self._sess,
                                           self._cj,
                                           username,
                                           logged_in=logged_in)
        self._rsvi_cache: Optional[Dict[str, Any]] = None

    @property
    def logged_in(self):
        return self._login_handler.logged_in

    def _init_cookiejar(self,
                        path: str,
                        cls: Type[CookieJar] = MozillaCookieJar) -> None:
        self._log.debug('Initialising cookie jar (%s) at %s', cls.__name__,
                        path)
        try:
            with open(path):
                pass
        except IOError:
            with open(path, 'w+'):
                pass
        try:
            self._cj = cls(path)  # type: ignore[arg-type]
        except TypeError:
            self._cj = cls()
        if hasattr(self._cj, 'load'):
            try:
                self._cj.load()  # type: ignore[attr-defined]
            except LoadError:
                self._log.debug('File %s for cookies does not yet exist', path)

    def login(self) -> None:
        self._login_handler.login()

    def remove_video_id_from_playlist(
            self,
            playlist_id: str,
            video_id: str,
            cache_values: Optional[bool] = False) -> None:
        """Removes a video from a playlist."""
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to login()'
                                      ' first')

        if cache_values and self._rsvi_cache:
            soup = self._rsvi_cache['soup']
            ytcfg = self._rsvi_cache['ytcfg']
            headers = self._rsvi_cache['headers']
        else:
            soup = self._download_page_soup(WATCH_LATER_URL)
            ytcfg = find_ytcfg(soup)
            headers = ytcfg_headers(ytcfg)
        if cache_values:
            self._rsvi_cache = dict(soup=soup, ytcfg=ytcfg, headers=headers)

        action = {
            'removedVideoId': video_id,
            'action': 'ACTION_REMOVE_VIDEO_BY_VIDEO_ID'
        }

        return (at_path(
            'status',
            cast(
                Mapping[str, Any],
                self._download_page(
                    f'https://www.youtube.com/youtubei/v1/browse/edit_playlist',
                    method='post',
                    params=dict(key=ytcfg['INNERTUBE_API_KEY']),
                    headers={
                        'Authorization':
                        self._authorization_sapisidhash_header(),
                        'x-goog-authuser': '0',
                        'x-origin': 'https://www.youtube.com',
                    },
                    json=dict(actions=[action],
                              playlistId=playlist_id,
                              params='CAFAAQ%3D%3D',
                              context=dict(
                                  client=context_client_body(ytcfg),
                                  request=dict(consistencyTokenJars=[],
                                               internalExperimentFlags=[]),
                              )),
                    return_json=True))) == 'STATUS_SUCCEEDED')

    def clear_watch_history(self) -> None:
        """Clears watch history."""
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        content = self._download_page_soup(HISTORY_URL)
        ytcfg = find_ytcfg(content)
        headers = ytcfg_headers(ytcfg)
        headers['x-spf-previous'] = HISTORY_URL
        headers['x-spf-referer'] = HISTORY_URL
        init_data = initial_data(content)
        params = {'name': 'feedbackEndpoint'}
        try:
            data = {
                'sej':
                json.dumps(
                    init_data['contents']['twoColumnBrowseResultsRenderer']
                    ['secondaryContents']['browseFeedActionsRenderer']
                    ['contents'][2]['buttonRenderer']['navigationEndpoint']
                    ['confirmDialogEndpoint']['content']
                    ['confirmDialogRenderer']['confirmButton']
                    ['buttonRenderer']['serviceEndpoint']),
                'csn':
                ytcfg['EVENT_ID'],
                'session_token':
                ytcfg['XSRF_TOKEN']
            }
        except KeyError:
            self._log.debug('Clear button is likely disabled. History is '
                            'likely empty')
            return
        self._download_page(SERVICE_AJAX_URL,
                            params=params,
                            data=data,
                            headers=headers,
                            return_json=True,
                            method='post')
        self._log.info('Successfully cleared history')

    def get_playlist_info(self, playlist_id: str) -> Iterator[PlaylistInfo]:
        """Get playlist information given a playlist ID."""
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        url = 'https://www.youtube.com/playlist?list={}'.format(playlist_id)
        content = self._download_page_soup(url)
        ytcfg = find_ytcfg(content)
        headers = ytcfg_headers(ytcfg)
        yt_init_data = initial_data(content)
        video_list_renderer: Optional[PlaylistVideoListRenderer] = None
        try:
            video_list_renderer = (
                yt_init_data['contents']['twoColumnBrowseResultsRenderer']
                ['tabs'][0]['tabRenderer']['content']['sectionListRenderer']
                ['contents'][0]['itemSectionRenderer']['contents'][0]
                ['playlistVideoListRenderer'])
        except KeyError as e:
            if e.args[0] == 'playlistVideoListRenderer':
                raise KeyError('This playlist might be empty.') from e
            raise e
        assert video_list_renderer is not None
        try:
            for item in video_list_renderer['contents']:
                if 'playlistVideoRenderer' in item:
                    yield item
                elif 'continuationItemRenderer' in item:
                    break
        except KeyError:
            yield from []
        endpoint = continuation = itct = None
        try:
            endpoint = (video_list_renderer['contents'][-1]
                        ['continuationItemRenderer']['continuationEndpoint'])
            continuation = endpoint['continuationCommand']['token']
            itct = endpoint['clickTrackingParams']
        except KeyError:
            pass
        if continuation and itct:
            while True:
                params = {
                    'ctoken': continuation,
                    'continuation': continuation,
                    'itct': itct
                }
                contents = cast(
                    BrowseAJAXSequence,
                    self._download_page(BROWSE_AJAX_URL,
                                        params=params,
                                        return_json=True,
                                        headers=headers))
                response = contents[1]['response']
                items = (
                    response['onResponseReceivedActions'][0]
                    ['appendContinuationItemsAction']['continuationItems'])
                for item in items:
                    if 'playlistVideoRenderer' in item:
                        yield item
                    elif 'continuationItemRenderer' in item:
                        try:
                            endpoint = (video_list_renderer['contents'][-1]
                                        ['continuationItemRenderer']
                                        ['continuationEndpoint'])
                            continuation = endpoint['continuationCommand'][
                                'token']
                            itct = endpoint['clickTrackingParams']
                        except KeyError:
                            pass
                        break
                if 'continuationItemRenderer' not in items[-1]:
                    break

    def clear_playlist(self, playlist_id: str) -> None:
        """
        Removes all videos from the specified playlist.
        Use `WL` for Watch Later.
        """
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        playlist_info = self.get_playlist_info(playlist_id)
        try:
            video_ids = list(
                map(lambda x: x['playlistVideoRenderer']['videoId'],
                    playlist_info))
        except KeyError:
            self._log.info('Caught KeyError. This probably means the playlist '
                           'is empty.')
            return
        for video_id in video_ids:
            self._log.debug('Deleting from playlist: video_id = %s', video_id)
            self.remove_video_id_from_playlist(playlist_id, video_id)

    def clear_watch_later(self) -> None:
        """Removes all videos from the 'Watch Later' playlist."""
        self.clear_playlist('WL')

    def get_history_info(self) -> Iterator[Mapping[str, Any]]:
        """Get information about the History playlist."""
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        content = self._download_page_soup(HISTORY_URL)
        init_data = initial_data(content)
        ytcfg = find_ytcfg(content)
        headers = ytcfg_headers(ytcfg)
        section_list_renderer = (
            init_data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]
            ['tabRenderer']['content']['sectionListRenderer'])
        next_continuation = None
        for section_list in section_list_renderer['contents']:
            try:
                yield from section_list['itemSectionRenderer']['contents']
            except KeyError:
                if 'continuationItemRenderer' in section_list:
                    next_continuation = dict(
                        continuation=(section_list['continuationItemRenderer']
                                      ['continuationEndpoint']
                                      ['continuationCommand']['token']),
                        clickTrackingParams=(
                            section_list['continuationItemRenderer']
                            ['continuationEndpoint']['clickTrackingParams']))
                    break
        if not next_continuation:
            try:
                next_continuation = (section_list_renderer['continuations'][0]
                                     ['nextContinuationData'])
            except KeyError as e:
                return
        assert next_continuation is not None
        params = dict(continuation=next_continuation['continuation'],
                      ctoken=next_continuation['continuation'],
                      itct=next_continuation['clickTrackingParams'])
        xsrf = ytcfg['XSRF_TOKEN']
        resp = None
        while True:
            tries = 0
            time = 0
            last_exception = None
            while tries < 5:
                if time:
                    sleep(time)
                try:
                    resp = cast(
                        BrowseAJAXSequence,
                        self._download_page(BROWSE_AJAX_URL,
                                            return_json=True,
                                            headers=headers,
                                            data={'session_token': xsrf},
                                            method='post',
                                            params=params))
                    break
                except HTTPError as e:
                    last_exception = e
                    tries += 1
                    time = 2**tries
            if last_exception:
                self._log.debug('Caught HTTP error: %s, text: %s',
                                last_exception, last_exception.response.text)
                break
            assert resp is not None
            contents = resp[1]['response']
            try:
                section_list_renderer = (
                    contents['onResponseReceivedActions'][0]
                    ['appendContinuationItemsAction']['continuationItems'])
            except KeyError as e:
                self._log.debug('Caught KeyError: %s. Possible keys: %s', e,
                                ', '.join(contents.keys()))
                break
            continuations = None
            for section_list in section_list_renderer:
                try:
                    yield from section_list['itemSectionRenderer']['contents']
                except KeyError as e:
                    if 'continuationItemRenderer' in section_list:
                        continuations = [
                            dict(nextContinuationData=dict(
                                continuation=(
                                    section_list['continuationItemRenderer']
                                    ['continuationEndpoint']
                                    ['continuationCommand']['token']),
                                clickTrackingParams=(
                                    section_list['continuationItemRenderer']
                                    ['continuationEndpoint']
                                    ['clickTrackingParams'])))
                        ]
                        break
                    raise e
            if not continuations:
                try:
                    continuations = section_list_renderer['continuations']
                except KeyError as e:
                    # Probably the end of the history
                    self._log.debug('Caught KeyError: %s. Possible keys: %s',
                                    e, ', '.join(section_list_renderer.keys()))
                    break
                except TypeError as e:
                    # Probably the end of the history
                    self._log.debug(
                        'Caught TypeError evaluating '
                        '"section_list_renderer[\'continuations\']": %s', e)
                    break
            xsrf = resp[1]['xsrf_token']
            assert continuations is not None
            next_cont = continuations[0]['nextContinuationData']
            params['itct'] = next_cont['clickTrackingParams']
            params['ctoken'] = next_cont['continuation']
            params['continuation'] = next_cont['continuation']

    def remove_video_ids_from_history(self, video_ids: Sequence[str]) -> bool:
        """Delete a history entry by video ID."""
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        if not video_ids:
            return False
        history_info = self.get_history_info()
        content = self._download_page_soup(HISTORY_URL)
        ytcfg = find_ytcfg(content)
        headers = ytcfg_headers(ytcfg)
        entries = [
            x for x in history_info
            if x['videoRenderer']['videoId'] in video_ids
        ]
        if not entries:
            return False
        codes = []
        for entry in entries:
            resp = cast(
                HasStringCode,
                self._download_page(
                    SERVICE_AJAX_URL,
                    return_json=True,
                    data=dict(
                        sej=json.dumps(entry['videoRenderer']['menu']
                                       ['menuRenderer']['topLevelButtons'][0]
                                       ['buttonRenderer']['serviceEndpoint']),
                        csn=ytcfg['EVENT_ID'],
                        session_token=ytcfg['XSRF_TOKEN']),
                    method='post',
                    headers=headers,
                    params=dict(name='feedbackEndpoint')))
            codes.append(resp['code'] == 'SUCCESS')
        return all(codes)

    def _authorization_sapisidhash_header(self) -> str:
        now = int(datetime.now().timestamp())
        sapisid: Optional[str] = None
        for cookie in self._cj:
            if cookie.name in ('SAPISID', '__Secure-3PAPISID'):
                sapisid = cookie.value
                break
        assert sapisid is not None
        m = hashlib.sha1()
        m.update(f'{now} {sapisid} https://www.youtube.com'.encode())
        return f'SAPISIDHASH {now}_{m.hexdigest()}'

    def _single_feedback_api_call(
            self,
            ytcfg: YtcfgDict,
            feedback_token: str,
            click_tracking_params: str = '',
            api_url: str = '/youtubei/v1/feedback') -> bool:
        return cast(
            Mapping[str, Any],
            self._download_page(
                f'https://www.youtube.com{api_url}',
                method='post',
                params=dict(key=ytcfg['INNERTUBE_API_KEY']),
                headers={
                    'Authority': 'www.youtube.com',
                    'Authorization': self._authorization_sapisidhash_header(),
                    'x-goog-authuser': '0',
                    'x-origin': 'https://www.youtube.com',
                },
                json=dict(context=dict(
                    clickTracking=dict(
                        clickTrackingParams=click_tracking_params),
                    client=context_client_body(ytcfg),
                    request=dict(consistencyTokenJars=[],
                                 internalExperimentFlags=[]),
                    user=dict(lockedSafetyMode=False))),
                          feedbackTokens=[feedback_token],
                          isFeedbackTokenUnencrypted=False,
                          shouldMerge=False),
                return_json=True))['feedbackResponses'][0]['isProcessed']

    def _toggle_history(self, page_url: str, contents_index: int) -> bool:
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        content = self._download_page_soup(page_url)
        ytcfg = find_ytcfg(content)
        info = at_path(('contents.twoColumnBrowseResultsRenderer.'
                        'secondaryContents.browseFeedActionsRenderer.contents.'
                        f'{contents_index}.buttonRenderer.navigationEndpoint.'
                        'confirmDialogEndpoint.content.confirmDialogRenderer.'
                        'confirmEndpoint'), initial_data(content))
        return self._single_feedback_api_call(
            ytcfg, info['feedbackEndpoint']['feedbackToken'],
            info['clickTrackingParams'],
            info['commandMetadata']['webCommandMetadata']['apiUrl'])

    def toggle_search_history(self) -> bool:
        """Pauses or resumes search history depending on the current state."""
        return self._toggle_history(SEARCH_HISTORY_URL, 2)

    def toggle_watch_history(self) -> bool:
        """Pauses or resumes watch history depending on the current state."""
        return self._toggle_history(WATCH_HISTORY_URL, 3)

    def _community_history(
            self,
            only_first_page: bool = False) -> Iterator[CommunityHistoryEntry]:
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        content = self._download_page_soup(COMMUNITY_HISTORY_URL)
        ytcfg = find_ytcfg(content)
        headers = ytcfg_headers(ytcfg)
        headers['x-spf-previous'] = COMMUNITY_HISTORY_URL
        headers['x-spf-referer'] = COMMUNITY_HISTORY_URL
        item_section = at_path(
            ('contents.twoColumnBrowseResultsRenderer.tabs.'
             '0.tabRenderer.content.sectionListRenderer.contents.0.'
             'itemSectionRenderer'), initial_data(content))
        info = item_section['contents']
        delete_action_path = (
            'actionMenu.menuRenderer.items.0.menuNavigationItemRenderer.'
            'navigationEndpoint.confirmDialogEndpoint.content.'
            'confirmDialogRenderer.confirmButton.buttonRenderer.'
            'serviceEndpoint.performCommentActionEndpoint.action')
        for api_entry in (x['commentHistoryEntryRenderer'] for x in info):
            yield make_community_history_entry(api_entry, delete_action_path)
        if (only_first_page or 'continuations' not in item_section
                or not item_section['continuations']):
            return
        has_continuations = True
        while has_continuations:
            for cont in item_section['continuations']:
                data = cast(
                    Sequence[Any],
                    self._download_page(
                        BROWSE_AJAX_URL,
                        method='post',
                        params=dict(
                            ctoken=(
                                cont['nextContinuationData']['continuation']),
                            continuation=(
                                cont['nextContinuationData']['continuation']),
                            itct=(cont['nextContinuationData']
                                  ['clickTrackingParams'])),
                        data=dict(session_token=ytcfg['XSRF_TOKEN']),
                        headers=headers,
                        return_json=True))
                item_section = (data[1]['response']['continuationContents']
                                ['itemSectionContinuation'])
                for api_entry in (x['commentHistoryEntryRenderer']
                                  for x in item_section['contents']):
                    yield make_community_history_entry(api_entry,
                                                       delete_action_path)
                has_continuations = ('continuations' in item_section
                                     and item_section['continuations'])

    def community_history(
            self,
            only_first_page: bool = False) -> Iterator[CommunityHistoryEntry]:
        yield from self._community_history(only_first_page)

    def delete_community_entry(
            self,
            action: str,
            api_url: str = '/youtubei/v1/comment/perform_comment_action',
            ytcfg: Optional[YtcfgDict] = None) -> bool:
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        if not ytcfg:
            content = self._download_page_soup(COMMUNITY_HISTORY_URL)
            ytcfg = find_ytcfg(content)
        return (at_path(
            'actionResults.0.status',
            cast(
                Mapping[str, Any],
                self._download_page(
                    f'https://www.youtube.com{api_url}',
                    method='post',
                    params=dict(key=ytcfg['INNERTUBE_API_KEY']),
                    headers={
                        'Authority': 'www.youtube.com',
                        'Authorization':
                        self._authorization_sapisidhash_header(),
                        'x-goog-authuser': '0',
                        'x-origin': 'https://www.youtube.com',
                    },
                    json=dict(
                        actions=[action],
                        context=dict(
                            clickTracking=dict(clickTrackingParams=''),
                            client=context_client_body(ytcfg),
                            request=dict(consistencyTokenJars=[],
                                         internalExperimentFlags=[]),
                            user=dict(
                                onBehalfOfUser=ytcfg['DELEGATED_SESSION_ID']))
                    ),
                    return_json=True))) == 'STATUS_SUCCEEDED')

    def clear_search_history(self) -> bool:
        """Clear search history."""
        if not self.logged_in:
            raise AuthenticationError('This method requires a call to '
                                      'login() first')
        content = self._download_page_soup(SEARCH_HISTORY_URL)
        return self._single_feedback_api_call(
            find_ytcfg(content),
            at_path(
                'contents.twoColumnBrowseResultsRenderer.'
                'secondaryContents.browseFeedActionsRenderer.'
                'contents.1.buttonRenderer.navigationEndpoint.'
                'confirmDialogEndpoint.content.confirmDialogRenderer.'
                'confirmEndpoint.feedbackEndpoint.feedbackToken',
                initial_data(content)))
