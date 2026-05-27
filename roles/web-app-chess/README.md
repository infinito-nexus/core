# Chess

## Description

**castling.club** is a federated chess server built on the ActivityPub protocol.  
It provides an open and decentralized way to play chess online, where games and moves are visible across the Fediverse.

## Overview

Instead of relying on closed platforms, castling.club uses an arbiter actor (“the King”) to validate moves and mediate matches.  
This ensures fair play, federation with platforms like Mastodon or Friendica, and community visibility of ongoing games.  
The service runs as a lightweight Node.js app backed by PostgreSQL.

## Features

- **Federated Chess Matches:** Challenge and play with others across the Fediverse.  
- **Rule Enforcement:** The arbiter validates each move for correctness.  
- **Open Identities:** Use your existing Fediverse account; no new silo account needed.  
- **Game Visibility:** Matches and moves can appear in social timelines.  
- **Lightweight Service:** Built with Node.js and PostgreSQL for efficiency.  

## Further Resources

- [castling.club GitHub Repository](https://github.com/stephank/castling.club)  
- [ActivityPub Specification (W3C)](https://www.w3.org/TR/activitypub/)  

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
