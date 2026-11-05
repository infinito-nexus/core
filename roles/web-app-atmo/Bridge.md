# Bridge

The `bridge` sidecar mirrors the calendar events of the platform PDS into [Mobilizon](../web-app-mobilizon/), which publishes them at `event.<primary domain>` and federates them over ActivityPub. The direction is one-way, AT Protocol to ActivityPub. The entry point is [bridge.py](./files/python/bridge.py); the record mapping, the mapping store, the PDS and Mobilizon clients and the mirror cycle live in the `atmo_bridge` package beside it.

## Scheduling

The service is rendered only when `services.bridge.enabled` is true, which defaults to `web-app-mobilizon` and `web-app-bluesky` both being in `group_names`. Without either partner the compose file carries no `bridge` service and the deploy runs without it.

## Cycle

Every `services.bridge.interval_seconds` the bridge:

1. lists the repositories of the platform PDS with `com.atproto.sync.listRepos`;
2. skips every deactivated repository and every repository whose `rev` it already mirrored;
3. lists the `community.lexicon.calendar.event` records of each changed repository with `com.atproto.repo.listRecords`;
4. creates a Mobilizon event for each new record, updates the event when the record's CID changed, and deletes the event when the record is gone;
5. stores the repository `rev` once all its changes are applied, and writes a heartbeat the container healthcheck reads.

A failed mutation leaves the repository `rev` unstored, so the next cycle plans the repository again. Mappings already written stay, so nothing is created twice. A mirrored event deleted by hand in Mobilizon is recreated on the next update of its record and forgotten on the next delete.

## Mobilizon identity

The bridge signs in to Mobilizon's GraphQL API as `atmo_bridge`, the local account `web-app-mobilizon-atmo-bridge` that [web-app-mobilizon](../web-app-mobilizon/meta/users.yml) declares. The account holds the Mobilizon role `user` and its own password, which the inventory pins for it like for every declared user, so no credential of the platform administrator reaches the bridge. `web-app-mobilizon` creates it with a profile whenever this role's `bridge` flag is on, and events are published as that profile. This needs Mobilizon's database login, which `web-app-mobilizon` switches off when its native login method is off.

## Mapping store

The store is the SQLite file `state.sqlite` in the `bridge_state` volume.

| Table | Columns | Purpose |
|---|---|---|
| `mirror` | `at_uri` (primary key), `did`, `at_cid`, `origin`, `mobilizon_event_id` (unique), `updated_at` | One row per mirrored record. |
| `repo_rev` | `did`, `rev` | Last repository revision mirrored. |
| `heartbeat` | `at` | Time of the last complete cycle. |

`origin` records the side the event was authored on, `atproto` for every row the bridge writes today. The unique index on `mobilizon_event_id` lets a future ActivityPub to AT Protocol path look an incoming Mobilizon event up with `Store.mirrored_from()` and recognise its own mirror before echoing it back.

## Field mapping

| Lexicon field | Mobilizon argument | Rule |
|---|---|---|
| `name` | `title` | Required; a record without it is not mirrored. |
| `description` | `description` | Plain text, HTML-escaped, blank lines become paragraphs. A link back to the event on atmo is appended. |
| `uris[].uri` | `description` | Appended as links after the atmo link. |
| `startsAt` | `beginsOn` | Required, converted to UTC; a record without it is not mirrored. |
| `endsAt` | `endsOn` | Converted to UTC; an end before the start stops the record from being mirrored. |
| `status` | `status` | `#scheduled` and `#rescheduled` become `CONFIRMED`, `#planned` and `#postponed` become `TENTATIVE`, `#cancelled` becomes `CANCELLED`. A missing status is the lexicon default `#scheduled`; an unknown value stops the record from being mirrored. |
| `mode` | `physicalAddress`, `onlineAddress` | `#inperson` maps the address, `#virtual` maps the online address, `#hybrid` maps both. A missing mode is the lexicon default `#inperson`; an unknown value stops the record from being mirrored. |
| first `community.lexicon.location.address` | `physicalAddress` | `street`, `locality`, `postalCode`, `region` and `country` keep their names, `name` becomes `description`. |
| first `community.lexicon.location.geo` or `community.lexicon.location.fsq` | `physicalAddress.geom` | `longitude;latitude`; its `name` fills `description` when the address has none. |
| first `community.lexicon.calendar.event#uri` location | `onlineAddress` | The location's `uri`. |
| — | `visibility`, `draft` | Always `PUBLIC` and `false`. |

## Unmapped fields

These fields have no Mobilizon counterpart. The bridge names every one it meets in its log, per record, instead of dropping it silently:

- `createdAt`: Mobilizon records its own publication time.
- `rsvpExpected`: Mobilizon has no such flag.
- any key outside the lexicon, for example atmo's `additionalData`, `preferences` or `media`;
- every location not consumed by the rules above, logged as `locations[<index>]:<type>`: further addresses and coordinates, `#uri` locations of in-person events, addresses of virtual events, and every `community.lexicon.location.hthree` cell;
- the `altitude` of a geo location and the `fsq_place_id` of a Foursquare location;
- an IANA time zone: the lexicon carries UTC offsets only, so Mobilizon shows the event in its own time zone.

## Out of scope

- RSVPs (`community.lexicon.calendar.rsvp`) are not mirrored.
- Events of accounts on other PDSes are not mirrored; the bridge reads the platform PDS only.
- The ActivityPub to AT Protocol direction needs an AT identity to write records as and is not implemented.
