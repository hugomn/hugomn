"""
Refreshes the profile card SVGs with live GitHub stats.

Runs daily via GitHub Actions. Queries the GitHub GraphQL API and rewrites
the numbers in dark_mode.svg and light_mode.svg by element id.

Stats engine adapted (and heavily simplified) from Andrew6rant/Andrew6rant.
"""
import datetime
import os

import requests
from dateutil import relativedelta
from lxml import etree

HEADERS = {'authorization': 'token ' + os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ.get('USER_NAME', 'hugomn')
API_URL = 'https://api.github.com/graphql'


def graphql(query, variables):
    response = requests.post(API_URL, json={'query': query, 'variables': variables}, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f'GraphQL request failed with {response.status_code}: {response.text}')
    payload = response.json()
    if 'errors' in payload:
        raise Exception(f'GraphQL errors: {payload["errors"]}')
    return payload['data']


def account_created_at():
    query = '''
    query($login: String!) {
        user(login: $login) { createdAt }
    }'''
    data = graphql(query, {'login': USER_NAME})
    return datetime.datetime.fromisoformat(data['user']['createdAt'].replace('Z', '+00:00'))


def follower_count():
    query = '''
    query($login: String!) {
        user(login: $login) { followers { totalCount } }
    }'''
    return graphql(query, {'login': USER_NAME})['user']['followers']['totalCount']


def repos_and_stars():
    query = '''
    query($login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
                totalCount
                edges { node { stargazers { totalCount } } }
                pageInfo { endCursor hasNextPage }
            }
        }
    }'''
    repos, stars, cursor = 0, 0, None
    while True:
        data = graphql(query, {'login': USER_NAME, 'cursor': cursor})['user']['repositories']
        repos = data['totalCount']
        stars += sum(edge['node']['stargazers']['totalCount'] for edge in data['edges'])
        if not data['pageInfo']['hasNextPage']:
            return repos, stars
        cursor = data['pageInfo']['endCursor']


def total_contributions(created):
    """The contributions calendar only accepts one-year windows, so walk them."""
    query = '''
    query($login: String!, $from: DateTime!, $to: DateTime!) {
        user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
                contributionCalendar { totalContributions }
            }
        }
    }'''
    total = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    window_start = created
    while window_start < now:
        window_end = min(window_start + datetime.timedelta(days=365), now)
        data = graphql(query, {
            'login': USER_NAME,
            'from': window_start.isoformat(),
            'to': window_end.isoformat(),
        })
        total += data['user']['contributionsCollection']['contributionCalendar']['totalContributions']
        window_start = window_end
    return total


def overwrite_svg(filename, values):
    tree = etree.parse(filename)
    root = tree.getroot()
    for element_id, value in values.items():
        element = root.find(f".//*[@id='{element_id}']")
        if element is None:
            raise Exception(f'Element #{element_id} not found in {filename}')
        element.text = f'{value:,}' if isinstance(value, int) else str(value)
    tree.write(filename, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    created = account_created_at()
    years = relativedelta.relativedelta(datetime.datetime.now(datetime.timezone.utc), created).years
    repos, stars = repos_and_stars()
    values = {
        'years_data': years,
        'commit_data': total_contributions(created),
        'star_data': stars,
        'repo_data': repos,
        'follower_data': follower_count(),
    }
    for filename in ('dark_mode.svg', 'light_mode.svg'):
        overwrite_svg(filename, values)
    print('Updated SVGs with:', values)
