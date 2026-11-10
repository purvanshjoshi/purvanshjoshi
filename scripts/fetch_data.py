"""Fetch contribution calendar and featured repos into data/profile.json.

Run by the daily GitHub Action before render_cards.py. Needs GITHUB_TOKEN in
the environment (the Action's token works for public contributions; use a
personal token with read:user to include private contribution counts).
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

LOGIN = "purvanshjoshi"
OUT = Path(__file__).resolve().parent.parent / "data" / "profile.json"

QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    pinnedItems(first: 6, types: REPOSITORY) {
      nodes {
        ... on Repository {
          name
          owner { login }
          description
          url
          stargazerCount
          forkCount
          primaryLanguage { name color }
        }
      }
    }
  }
}
"""


def graphql(token, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": "bearer " + token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        sys.exit("GraphQL error: " + json.dumps(body["errors"]))
    return body["data"]


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    user = graphql(token, QUERY, {"login": LOGIN})["user"]
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [
        {"date": d["date"], "count": d["contributionCount"]}
        for week in calendar["weeks"]
        for d in week["contributionDays"]
    ]
    repos = [
        {
            "owner": r["owner"]["login"],
            "name": r["name"],
            "description": r["description"] or "",
            "url": r["url"],
            "stars": r["stargazerCount"],
            "forks": r["forkCount"],
            "language": (r["primaryLanguage"] or {}).get("name"),
            "language_color": (r["primaryLanguage"] or {}).get("color"),
        }
        for r in user["pinnedItems"]["nodes"]
    ]
    data = {
        "login": LOGIN,
        "name": user["name"],
        "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_contributions": calendar["totalContributions"],
        "days": days,
        "repos": repos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print("wrote %s (%d days, %d repos)" % (OUT, len(days), len(repos)))


if __name__ == "__main__":
    main()
