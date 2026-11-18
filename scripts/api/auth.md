# Texas Bill Atlas auth.md

## Audience

AI agents, crawlers and scripts reading Texas Bill Atlas (https://billatlas.org/) and its agent edition
(https://agent.billatlas.org/) on behalf of a person or for their own index.

## Registration

None. There are no accounts, API keys, OAuth flows or registration endpoints, and none are planned. Do not look for
`/agent/auth`, an authorization server or protected-resource metadata: they do not exist.

## Supported methods

- `anonymous`: every public endpoint is open to anonymous requests over HTTPS. Send a descriptive `User-Agent`.
- `view-only link` (optional, given by a person): lets you follow that person's watchlist. See below.

## Credentials

No credential is issued or accepted for public data. Do not send `Authorization` headers; they are ignored.

### A person's watchlist

People who sync their watchlist have two links of the same shape, `https://billatlas.org/#watchlist?sync=<key>`:
a **view-only link**, safe to share, and an **edit link**, which works like a password. You may ask a person for
their *view-only* link (Watchlist page, "Copy view-only link"). Never ask for the edit link.

Read it only through the watchlist feed: `GET https://billatlas.org/api/sync/feed/<key>.xml` (RSS of every
watched bill's recorded actions and published reviews). The feed accepts view-only keys and answers 404 for an edit key, so if it 404s,
tell the person they may have shared their private edit link and should copy the view-only one instead. Do not
send keys anywhere else, never store them beyond the task the person gave you, and never create sync links.

## Limits

Search (`https://agent.billatlas.org/search`) is rate limited per visitor; on HTTP 429, wait and retry. Every other
file is static: bill data is rebuilt hourly, so polling it more than once an hour gains nothing; review files
under `/live/luna/` change every few minutes while reviews run.

## Where to start

- Guide: https://agent.billatlas.org/llms.txt
- API catalog (RFC 9727): https://billatlas.org/.well-known/api-catalog
- OpenAPI description: https://billatlas.org/openapi.json
