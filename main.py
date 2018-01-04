import asyncio
import logging
import sys
from time import mktime

import aiohttp
import feedparser
import yaml
from raven import Client
from wallabag_api.wallabag import Wallabag

import github_stars

logger = logging.getLogger()
logger.handlers = []
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

with open("config.yaml", 'r') as stream:
    try:
        config = yaml.load(stream)
    except (yaml.YAMLError, FileNotFoundError) as exception:
        config = None
        exit(1)

ch = logging.StreamHandler(stream=sys.stdout)
ch.setLevel(logging.WARNING if "debug" not in config or not config["debug"] else logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)

fh = logging.FileHandler('debug.log')
fh.setFormatter(formatter)
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)

with open("sites.yaml", 'r') as stream:
    try:
        sites = yaml.load(stream)
    except (yaml.YAMLError, FileNotFoundError) as exception:
        logger.error(exception)
        sites = None
        exit(1)

if "sentry_url" in config and ("debug" not in config or not config["debug"]):
    client = Client(
        dsn=config["sentry_url"],
        processors=(
            'raven.processors.SanitizePasswordsProcessor',
        )
    )


async def fetch(session, url):
    async with session.get(url) as response:
        return await response.text()


async def main(loop, sites):
    token = await Wallabag.get_token(**config["wallabag"])

    async with aiohttp.ClientSession(loop=loop) as session:
        wall = Wallabag(host=config["wallabag"]["host"], client_secret=config["wallabag"]["client_secret"],
                        client_id=config["wallabag"]["client_id"], token=token, aio_sess=session)

        sites = github_stars.get_starred_repos(config["github_username"], sites)

        await asyncio.gather(*[handle_feed(session, wall, sitetitle, site) for sitetitle, site in sites.items()])


async def handle_feed(session, wall, sitetitle, site):
    logger.info(sitetitle + ": Downloading feed")
    rss = await fetch(session, site["url"])
    logger.info(sitetitle + ": Parsing feed")
    f = feedparser.parse(rss)
    logger.debug(sitetitle + ": finished parsing")
    # feedtitle = f["feed"]["title"]
    if "latest_article" in site:
        for article in f.entries:
            if article.title == site["latest_article"]:
                logger.debug("already added: " + article.title)
                break
            logger.info(article.title + ": article found")
            taglist = [sitetitle]
            if site["tags"]:
                taglist.extend(site["tags"])
            tags = ",".join(taglist)
            if "published_parsed" in article:
                published = mktime(article.published_parsed)
            elif "updated_parsed" in article:
                published = mktime(article.updated_parsed)
            else:
                published = None
            logger.info(article.title + ": add to wallabag")
            if "github" in site and site["github"]:
                title = sitetitle + ": " + article.title
            else:
                title = article.title
            if "debug" not in config or not config["debug"]:
                await wall.post_entries(url=article.link, title=title, tags=tags)
    else:
        logger.debug(sitetitle + ": no latest_article")
    if f.entries:
        sites[sitetitle]["latest_article"] = f.entries[0].title


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop, sites))
    with open("sites.yaml", 'w') as stream:
        yaml.dump(sites, stream, default_flow_style=False)
