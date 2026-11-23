"""Application metadata."""

__all__ = [
    'APP_AUTHOR',
    'APP_CONCEPT',
    'APP_DISPLAY_NAME',
    'APP_DISCORD',
    'APP_LOGIC',
    'APP_NAME',
    'APP_REPO',
    'APP_UPDATE_REPO',
    'APP_VERSION',
    'WINDOWS_ENV_PROXY_BACKEND_PORT',
    'app_discord',
    'set_app_discord',
]

from importlib.metadata import PackageNotFoundError, metadata as distribution_metadata

from fleasion import __version__

APP_VERSION = __version__


def _project_url(label: str) -> str:
    """Read a labeled project URL from bundled distribution metadata."""
    try:
        values = distribution_metadata('fleasion').get_all('Project-URL') or []
    except PackageNotFoundError:
        return ''

    wanted_label = label.casefold()
    for value in values:
        current_label, separator, url = value.partition(',')
        if separator and current_label.strip().casefold() == wanted_label:
            return url.strip()
    return ''


APP_NAME = 'MVSDsion'
APP_DISPLAY_NAME = APP_NAME
APP_AUTHOR = '@8ar__, @dis_spencer, @1_v, @yeha.'
APP_LOGIC = '@blockce, @0100152000022000, @emk530'
APP_CONCEPT = '@cro.p'
APP_DISCORD = 'discord.gg/hXyhKehEZF'
_discord_override = ''


def app_discord() -> str:
    """The Discord invite the website set this session, else the built-in one."""
    return _discord_override or APP_DISCORD


def set_app_discord(value: str) -> None:
    """Set (``''`` clears) the website's Discord invite; only invite-like values stick."""
    global _discord_override  # noqa: PLW0603 - a single process-wide setting
    text = value.strip()
    prefixes = ('http://', 'https://', 'discord.gg/', 'discord.com/', 'discordapp.com/')
    _discord_override = text if text.startswith(prefixes) else ''
APP_REPO = _project_url('Repository')
# MVSDsion never installs Fleasion releases, so the updater has no source
APP_UPDATE_REPO = ''
# MVSDsion uses its own Windows backend port so it never collides with Fleasion
WINDOWS_ENV_PROXY_BACKEND_PORT = 58445
