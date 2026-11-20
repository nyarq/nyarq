import os
import math
import random
import requests
from datetime import datetime, timedelta

# GitHub API configuration
TOKEN = os.environ.get('GITHUB_TOKEN', '')
USERNAME = os.environ.get('PROFILE_USER', 'nyarq')
CURRENT_YEAR = datetime.now().year

HEADERS = {
    'Authorization': f'bearer {TOKEN}',
    'Content-Type': 'application/json',
}

# Purple on near-black. Change these values to retheme every card at once.
PALETTE = {
    'ground': '#0a0910',   # card background (almost black)
    'text': '#ece8ff',     # numbers
    'muted': '#958db3',    # labels
    'accent': '#a78bfa',   # ring, bars, title
    'glow': '#6d28d9',     # nebula behind the ring
    'spark': '#f0abfc',    # planet, peak bar, some stars
    'line': '#a78bfa',
    'lineAlpha': '0.20',
    'edgeAlpha': '0.30',
    'trackAlpha': '0.14',
}

STATS_PATH = 'github-stats.svg'
HOURS_PATH = 'github-hours.svg'

SERIF = "'Iowan Old Style','Palatino Linotype','Book Antiqua',Palatino,Georgia,serif"
MONO = "'SF Mono','SFMono-Regular','Cascadia Mono','Segoe UI Mono','Roboto Mono','DejaVu Sans Mono',monospace"

# Fixed seed: the same sky every day, so the committed SVG does not churn.
STAR_SEED = 11
STAR_COUNT = 55

RING_RADIUS = 42
RING_LENGTH = 2 * math.pi * RING_RADIUS

TIMEZONE_OFFSET = timedelta(hours=9)
TIMEZONE_LABEL = 'Asia/Seoul'

COMMIT_PAGE_LIMIT = 10
WEEKDAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']

CARD_WIDTH = 495
CARD_HEIGHT = 208
HOURS_CARD_WIDTH = 495
HOURS_CARD_HEIGHT = 190

QUERY = '''
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes { stargazers { totalCount } }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestReviewContributions
    }
    pullRequests { totalCount }
    issues { totalCount }
  }
}
'''

REPOS_QUERY = '''
query($login: String!) {
  user(login: $login) {
    id
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes {
        name
        owner { login }
      }
    }
  }
}
'''

HISTORY_QUERY = '''
query($owner: String!, $name: String!, $author: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(author: {id: $author}, first: 100, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes { committedDate }
          }
        }
      }
    }
  }
}
'''


def graphql(query, variables):
    """Run one GraphQL query and return its data, raising on API errors."""
    resp = requests.post(
        'https://api.github.com/graphql',
        headers=HEADERS,
        json={'query': query, 'variables': variables},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get('errors'):
        raise RuntimeError(payload['errors'][0].get('message', 'GraphQL error'))
    return payload['data']


def fetchStats():
    user = graphql(QUERY, {'login': USERNAME})['user']
    return {
        'name': user['name'] or USERNAME,
        'stars': sum(r['stargazers']['totalCount'] for r in user['repositories']['nodes']),
        'commits': user['contributionsCollection']['totalCommitContributions'],
        'reviews': user['contributionsCollection']['totalPullRequestReviewContributions'],
        'prs': user['pullRequests']['totalCount'],
        'issues': user['issues']['totalCount'],
        'followers': user['followers']['totalCount'],
    }


def fetchCommitHours():
    """Bucket the author's commits on each owned repo by local hour and weekday."""
    account = graphql(REPOS_QUERY, {'login': USERNAME})['user']
    authorId = account['id']

    hours = [0] * 24
    days = [0] * 7
    total = 0

    for repo in account['repositories']['nodes']:
        cursor = None
        for _ in range(COMMIT_PAGE_LIMIT):
            branch = graphql(HISTORY_QUERY, {
                'owner': repo['owner']['login'],
                'name': repo['name'],
                'author': authorId,
                'after': cursor,
            })['repository']['defaultBranchRef']
            if not branch:
                break  # empty repository
            history = branch['target'].get('history')
            if not history:
                break

            for node in history['nodes']:
                stamp = datetime.strptime(node['committedDate'], '%Y-%m-%dT%H:%M:%SZ') + TIMEZONE_OFFSET
                hours[stamp.hour] += 1
                days[stamp.weekday()] += 1
                total += 1

            if not history['pageInfo']['hasNextPage']:
                break
            cursor = history['pageInfo']['endCursor']

    return {'hours': hours, 'days': days, 'total': total}


def normalCdf(mean, sigma, x):
    z = (x - mean) / (sigma * math.sqrt(2))
    return 0.5 * (1 + math.erf(z))


def calculateRank(stats):
    """Same weighting as github-readme-stats: (value, median, weight)."""
    metrics = [
        (stats['commits'], 250, 2),
        (stats['prs'], 50, 3),
        (stats['issues'], 25, 1),
        (stats['reviews'], 2, 1),
        (stats['stars'], 50, 4),
        (stats['followers'], 10, 1),
    ]
    totalWeight = sum(w for _, _, w in metrics)
    score = sum(w * normalCdf(median, median, value) for value, median, w in metrics) / totalWeight
    percentile = (1 - score) * 100

    for limit, rank in [(1, 'S'), (12.5, 'A+'), (25, 'A'), (37.5, 'A-'), (50, 'B+'),
                        (62.5, 'B'), (75, 'B-'), (87.5, 'C+')]:
        if percentile < limit:
            return rank, percentile
    return 'C', percentile


def starfield(blocked, ringCentre, ringRadius):
    """Scatter stars over empty ground only (rejection sampling, fixed seed)."""
    p = PALETTE
    rng = random.Random(STAR_SEED)
    marks = []
    attempts = 0
    while len(marks) < STAR_COUNT and attempts < 6000:
        attempts += 1
        starX = round(rng.uniform(5, CARD_WIDTH - 5), 1)
        starY = round(rng.uniform(5, CARD_HEIGHT - 5), 1)
        radius = round(rng.uniform(0.5, 1.7), 2)
        alpha = round(rng.uniform(0.25, 0.9), 2)
        tone = rng.random()
        fill = p['accent'] if tone < 0.22 else p['spark'] if tone < 0.32 else p['text']

        sparkle = len(marks) % 9 == 4
        arm = round(radius * 2.6, 2)
        reach = arm if sparkle else radius
        if any(x0 - reach <= starX <= x1 + reach and y0 - reach <= starY <= y1 + reach
               for x0, y0, x1, y1 in blocked):
            continue
        if math.dist((starX, starY), ringCentre) < ringRadius + 14 + reach:
            continue

        if sparkle:
            marks.append(
                f'    <g stroke="{fill}" stroke-opacity="{alpha}" stroke-width="0.7" stroke-linecap="round">\n'
                f'      <line x1="{starX - arm}" y1="{starY}" x2="{starX + arm}" y2="{starY}"/>\n'
                f'      <line x1="{starX}" y1="{starY - arm}" x2="{starX}" y2="{starY + arm}"/>\n'
                f'    </g>'
            )
        else:
            marks.append(f'    <circle cx="{starX}" cy="{starY}" r="{radius}" fill="{fill}" fill-opacity="{alpha}"/>')
    return '\n'.join(marks)


def escape(text):
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def generateStatsSvg(stats, path):
    p = PALETTE
    rank, percentile = calculateRank(stats)

    score = max(0.0, min(1.0, 1 - percentile / 100))
    ringFill = RING_LENGTH * score
    orbitAngle = math.radians(-90 + 360 * score)
    planetX = RING_RADIUS * math.cos(orbitAngle)
    planetY = RING_RADIUS * math.sin(orbitAngle)

    name = escape(stats['name'])

    cells = [
        ('STARS EARNED', stats['stars']),
        (f'COMMITS &#183; {CURRENT_YEAR}', stats['commits']),
        ('PULL REQUESTS', stats['prs']),
        ('ISSUES OPENED', stats['issues']),
        ('CODE REVIEWS', stats['reviews']),
        ('FOLLOWERS', stats['followers']),
    ]

    cellMarkup = []
    blocked = [(16, 18, 262, 48), (366, 22, 478, 48), (20, 46, 475, 60)]
    for index, (label, value) in enumerate(cells):
        cellX = 28 + (index % 2) * 162
        labelY = 78 + (index // 2) * 46
        blocked.append((cellX - 10, labelY - 15, cellX + 152, labelY + 30))
        cellMarkup.append(
            f'  <text x="{cellX}" y="{labelY}" font-family="{MONO}" font-size="12.5" '
            f'letter-spacing="0.9" fill="{p["muted"]}">{label}</text>\n'
            f'  <text x="{cellX}" y="{labelY + 22}" font-family="{MONO}" font-size="23" '
            f'font-weight="600" fill="{p["text"]}">{value}</text>'
        )
    statGrid = '\n'.join(cellMarkup)
    stars = starfield(blocked, (410, 130), RING_RADIUS)

    svg = f'''<svg width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{name} GitHub stats, rank {rank}">
  <defs>
    <clipPath id="gs-card">
      <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" rx="6"/>
    </clipPath>
    <radialGradient id="gs-nebula" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="{p["glow"]}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="{p["glow"]}" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <g clip-path="url(#gs-card)">
    <rect x="0" y="0" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" fill="{p["ground"]}"/>
    <ellipse cx="410" cy="130" rx="118" ry="102" fill="url(#gs-nebula)"/>
{stars}
  </g>

  <text x="28" y="38" font-family="{SERIF}" font-size="21" fill="{p["accent"]}">{name}</text>
  <text x="467" y="38" text-anchor="end" font-family="{MONO}" font-size="12" fill="{p["muted"]}">@{USERNAME}</text>
  <line x1="28" y1="53" x2="467" y2="53" stroke="{p["line"]}" stroke-opacity="{p["lineAlpha"]}"/>

{statGrid}

  <g transform="translate(410,130)">
    <circle r="{RING_RADIUS}" fill="none" stroke="{p["line"]}" stroke-opacity="{p["trackAlpha"]}" stroke-width="5"/>
    <circle r="{RING_RADIUS}" fill="none" stroke="{p["accent"]}" stroke-width="5"
      stroke-dasharray="{ringFill:.1f} {RING_LENGTH:.1f}" stroke-linecap="round" transform="rotate(-90)"/>
    <circle cx="{planetX:.1f}" cy="{planetY:.1f}" r="3.4" fill="{p["spark"]}"/>
    <text y="-2" text-anchor="middle" font-family="{SERIF}" font-size="28" fill="{p["text"]}">{rank}</text>
    <text y="20" text-anchor="middle" font-family="{MONO}" font-size="11.5" letter-spacing="0.9" fill="{p["muted"]}">TOP {percentile:.0f}%</text>
  </g>

  <rect x="0.5" y="0.5" width="{CARD_WIDTH - 1}" height="{CARD_HEIGHT - 1}" rx="6" fill="none" stroke="{p["line"]}" stroke-opacity="{p["edgeAlpha"]}"/>
</svg>'''

    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print(f'Generated {path} - Rank: {rank} (top {percentile:.1f}%)')


def generateHoursSvg(activity, path):
    p = PALETTE
    hours = activity['hours']
    days = activity['days']

    ceiling = max(hours) or 1
    peak = max(range(24), key=lambda hour: hours[hour])
    busiest = max(range(7), key=lambda day: days[day])

    chartLeft, chartRight = 28, 467
    baseline, barCeiling = 128, 56
    gap = 4
    barWidth = (chartRight - chartLeft - gap * 23) / 24

    bars = []
    for hour, count in enumerate(hours):
        height = max(barCeiling * count / ceiling, 1.5)
        x = chartLeft + hour * (barWidth + gap)
        fill = p['spark'] if hour == peak and count else p['accent']
        bars.append(
            f'  <rect x="{x:.1f}" y="{baseline - height:.1f}" width="{barWidth:.1f}" '
            f'height="{height:.1f}" rx="1.5" fill="{fill}" '
            f'fill-opacity="{0.35 + 0.65 * count / ceiling:.2f}"/>'
        )
    barMarkup = '\n'.join(bars)

    ticks = []
    for hour in range(0, 24, 3):
        x = chartLeft + hour * (barWidth + gap) + barWidth / 2
        ticks.append(
            f'  <text x="{x:.1f}" y="143" text-anchor="middle" font-family="{MONO}" '
            f'font-size="9.5" fill="{p["muted"]}">{hour:02d}</text>'
        )
    tickMarkup = '\n'.join(ticks)

    cells = [
        ('PEAK HOUR', f'{peak:02d}:00'),
        ('BUSIEST DAY', WEEKDAYS[busiest]),
        ('COMMITS READ', f'{activity["total"]:,}'),
    ]
    cellMarkup = []
    for index, (label, value) in enumerate(cells):
        cellX = 28 + index * 152
        cellMarkup.append(
            f'  <text x="{cellX}" y="165" font-family="{MONO}" font-size="11" '
            f'letter-spacing="0.9" fill="{p["muted"]}">{label}</text>\n'
            f'  <text x="{cellX}" y="182" font-family="{MONO}" font-size="17" '
            f'font-weight="600" fill="{p["text"]}">{value}</text>'
        )
    figureGrid = '\n'.join(cellMarkup)

    svg = f'''<svg width="{HOURS_CARD_WIDTH}" height="{HOURS_CARD_HEIGHT}" viewBox="0 0 {HOURS_CARD_WIDTH} {HOURS_CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Commits by hour of day, peak at {peak:02d}:00 {TIMEZONE_LABEL}">
  <rect x="0" y="0" width="{HOURS_CARD_WIDTH}" height="{HOURS_CARD_HEIGHT}" rx="6" fill="{p["ground"]}"/>

  <text x="28" y="38" font-family="{SERIF}" font-size="21" fill="{p["accent"]}">Active hours</text>
  <text x="467" y="38" text-anchor="end" font-family="{MONO}" font-size="12" fill="{p["muted"]}">{TIMEZONE_LABEL}</text>
  <line x1="28" y1="53" x2="467" y2="53" stroke="{p["line"]}" stroke-opacity="{p["lineAlpha"]}"/>

{barMarkup}
  <line x1="28" y1="{baseline + 0.5}" x2="467" y2="{baseline + 0.5}" stroke="{p["line"]}" stroke-opacity="{p["lineAlpha"]}"/>
{tickMarkup}

{figureGrid}

  <rect x="0.5" y="0.5" width="{HOURS_CARD_WIDTH - 1}" height="{HOURS_CARD_HEIGHT - 1}" rx="6" fill="none" stroke="{p["line"]}" stroke-opacity="{p["edgeAlpha"]}"/>
</svg>'''

    with open(path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print(f'Generated {path} - peak {peak:02d}:00, {activity["total"]} commits read')


if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('GITHUB_TOKEN is not set')
    generateStatsSvg(fetchStats(), STATS_PATH)
    generateHoursSvg(fetchCommitHours(), HOURS_PATH)
