/**
 * Binds existing n8n accounts to their Keycloak subject in auth_identity
 * (providerType 'oidc'), the key hooks.js signs SSO users in by. Prints one
 * "skipped <username>: <reason>" line per local account it leaves unbound,
 * then CHANGED or OK.
 *
 * Environment:
 *   N8N_SSO_DIRECTORY_USERS: JSON list of {username, email, emailVerified, id}
 *     from web-app-keycloak utils/directory_users.yml.
 *   DB_TYPE, DB_POSTGRESDB_HOST, DB_POSTGRESDB_PORT, DB_POSTGRESDB_DATABASE,
 *   DB_POSTGRESDB_USER, DB_POSTGRESDB_PASSWORD: n8n's own connection settings.
 */

const PROVIDER = 'oidc'
const OWNER_ROLE = 'global:owner'

/**
 * Args:
 *   directory: keycloak_directory_users entries.
 *   accounts: n8n users as {id, email, roleSlug, subjects}, subjects being the
 *     account's oidc providerIds.
 *   holders: map of oidc providerId to the userId holding it.
 * Returns: {bind: [{userId, subject}], skipped: [{username, reason}]}.
 */
function plan(directory, accounts, holders) {
    const byEmail = new Map(accounts.map((account) => [String(account.email).toLowerCase(), account]))
    const bind = []
    const skipped = []
    for (const entry of directory) {
        const account = byEmail.get(String(entry.email).toLowerCase())
        if (!account || account.roleSlug === OWNER_ROLE || account.subjects.includes(entry.id)) {
            continue
        }
        let reason = null
        if (entry.emailVerified !== true) {
            reason = 'the Keycloak email is not verified'
        } else if (account.subjects.length > 0) {
            reason = 'the account is linked to another identity'
        } else if (holders.has(entry.id)) {
            reason = 'the identity is linked to another account'
        }
        if (reason) {
            skipped.push({ username: entry.username, reason })
        } else {
            bind.push({ userId: account.id, subject: entry.id })
        }
    }
    return { bind, skipped }
}

async function main() {
    if (process.env.DB_TYPE !== 'postgresdb') {
        throw new Error(`unsupported DB_TYPE ${process.env.DB_TYPE}`)
    }
    const directory = JSON.parse(process.env.N8N_SSO_DIRECTORY_USERS)
    const { Client } = require('pg')
    const client = new Client({
        host: process.env.DB_POSTGRESDB_HOST,
        port: parseInt(process.env.DB_POSTGRESDB_PORT, 10),
        database: process.env.DB_POSTGRESDB_DATABASE,
        user: process.env.DB_POSTGRESDB_USER,
        password: process.env.DB_POSTGRESDB_PASSWORD
    })
    await client.connect()
    try {
        const users = await client.query('SELECT id, email, "roleSlug" FROM "user" WHERE email IS NOT NULL')
        const identities = await client.query(
            'SELECT "userId", "providerId" FROM auth_identity WHERE "providerType" = $1',
            [PROVIDER]
        )
        const holders = new Map(identities.rows.map((row) => [row.providerId, row.userId]))
        const accounts = users.rows.map((row) => ({
            ...row,
            subjects: identities.rows.filter((identity) => identity.userId === row.id).map((identity) => identity.providerId)
        }))
        const { bind, skipped } = plan(directory, accounts, holders)
        for (const { username, reason } of skipped) {
            console.log(`skipped ${username}: ${reason}`)
        }
        for (const { userId, subject } of bind) {
            await client.query(
                'INSERT INTO auth_identity ("userId", "providerId", "providerType", "createdAt", "updatedAt") VALUES ($1, $2, $3, NOW(), NOW())',
                [userId, subject, PROVIDER]
            )
        }
        console.log(bind.length > 0 ? 'CHANGED' : 'OK')
    } finally {
        await client.end()
    }
}

// `node -` leaves require.main unset, a test's require sets it to the test file
if (require.main === undefined) {
    main().catch((error) => {
        process.stderr.write(`FAILED ${error.message}\n`)
        process.exit(1)
    })
}

module.exports = { plan }
