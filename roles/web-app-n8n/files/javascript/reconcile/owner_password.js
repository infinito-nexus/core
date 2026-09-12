/**
 * Prints CHANGED when it rewrote the owner's hash, OK when it already matched or
 * the owner does not exist yet.
 *
 * Environment:
 *   N8N_OWNER_EMAIL:    the owner account's email.
 *   N8N_OWNER_PASSWORD: the password the deployment wants it to have.
 *   DB_TYPE, DB_POSTGRESDB_HOST, DB_POSTGRESDB_PORT, DB_POSTGRESDB_DATABASE,
 *   DB_POSTGRESDB_USER, DB_POSTGRESDB_PASSWORD: n8n's own connection settings.
 */

// nocheck: mirrored-unit-test - resolves bcryptjs and pg from the n8n container's
// own node_modules and writes the hash straight into the live user row; outside that
// container the requires do not resolve

const bcrypt = require('bcryptjs')
const { Client } = require('pg')

const email = process.env.N8N_OWNER_EMAIL
const password = process.env.N8N_OWNER_PASSWORD

function fail(message) {
    process.stderr.write(`FAILED ${message}\n`)
    process.exit(1)
}

async function main() {
    if (!email || !password) {
        fail('N8N_OWNER_EMAIL and N8N_OWNER_PASSWORD are required')
    }
    if (process.env.DB_TYPE !== 'postgresdb') {
        fail(`unsupported DB_TYPE ${process.env.DB_TYPE}`)
    }

    const client = new Client({
        host: process.env.DB_POSTGRESDB_HOST,
        port: parseInt(process.env.DB_POSTGRESDB_PORT, 10),
        database: process.env.DB_POSTGRESDB_DATABASE,
        user: process.env.DB_POSTGRESDB_USER,
        password: process.env.DB_POSTGRESDB_PASSWORD
    })
    await client.connect()
    try {
        const found = await client.query('SELECT password FROM "user" WHERE email = lower($1)', [email])
        if (found.rowCount === 0) {
            console.log('OK')
            return
        }
        const stored = found.rows[0].password
        if (stored && bcrypt.compareSync(password, stored)) {
            console.log('OK')
            return
        }
        const hash = bcrypt.hashSync(password, 10)
        await client.query('UPDATE "user" SET password = $1 WHERE email = lower($2)', [hash, email])
        console.log('CHANGED')
    } finally {
        await client.end()
    }
}

main().catch((error) => fail(error.message))
