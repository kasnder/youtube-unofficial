from typing_extensions import Final

__all__ = (
    'BROWSE_AJAX_URL',
    'CHALLENGE_URL',
    'HISTORY_URL',
    'HOMEPAGE_URL',
    'LOGIN_URL',
    'LOOKUP_URL',
    'NETRC_MACHINE',
    'SERVICE_AJAX_URL',
    'TFA_URL',
    'USER_AGENT',
    'WATCH_LATER_URL',
)

NETRC_MACHINE: Final = 'youtube'
USER_AGENT: Final = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/74.0.3729.108 Safari/537.36')

BROWSE_AJAX_URL: Final = 'https://www.youtube.com/browse_ajax'
CHALLENGE_URL: Final = 'https://accounts.google.com/_/signin/sl/challenge'
HISTORY_URL: Final = 'https://www.youtube.com/feed/history'
HOMEPAGE_URL: Final = 'https://www.youtube.com'
LOGIN_URL: Final = 'https://accounts.google.com/ServiceLogin'
LOOKUP_URL: Final = 'https://accounts.google.com/_/signin/sl/lookup'
SERVICE_AJAX_URL: Final = 'https://www.youtube.com/service_ajax'
TFA_URL: Final = 'https://accounts.google.com/_/signin/challenge?hl=en&TL={0}'
WATCH_LATER_URL: Final = 'https://www.youtube.com/playlist?list=WL'
