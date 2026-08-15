/**
 * Converge the stored password of the Flowise MCP API identity.
 *
 * Flowise only ever accepts a password at registration, and registration works
 * once. A redeploy that hands the role a rotated credential therefore meets an
 * account whose bcrypt hash still encodes the previous one, and every later
 * login answers "Incorrect Email or Password". This writes the desired hash
 * straight into the user row, which is the same value the registration path
 * would have stored.
 *
 * Runs inside the Flowise container and reads its own DATABASE_* environment.
 * Prints CHANGED when it rewrote the hash, OK when it already matched or the
 * account does not exist yet.
 *
 * Environment:
 *   FLOWISE_ADMIN_EMAIL:      the API identity's email.
 *   FLOWISE_ADMIN_PASSWORD:   the password the deployment wants it to have.
 *   PASSWORD_SALT_HASH_ROUNDS: bcrypt cost, defaulting to the Flowise default.
 *   DATABASE_TYPE, DATABASE_HOST, DATABASE_PORT, DATABASE_NAME,
 *   DATABASE_USER, DATABASE_PASSWORD: Flowise's own connection settings.
 */

const bcrypt = require('bcryptjs')
const { Client } = require('pg')

const email = process.env.FLOWISE_ADMIN_EMAIL
const password = process.env.FLOWISE_ADMIN_PASSWORD
const rounds = parseInt(process.env.PASSWORD_SALT_HASH_ROUNDS || '10', 10)

function fail(message) {
    process.stderr.write(`FAILED ${message}\n`)
    process.exit(1)
}

async function main() {
    if (!email || !password) {
        fail('FLOWISE_ADMIN_EMAIL and FLOWISE_ADMIN_PASSWORD are required')
    }
    if (process.env.DATABASE_TYPE !== 'postgres') {
        fail(`unsupported DATABASE_TYPE ${process.env.DATABASE_TYPE}`)
    }

    const client = new Client({
        host: process.env.DATABASE_HOST,
        port: parseInt(process.env.DATABASE_PORT || '5432', 10),
        database: process.env.DATABASE_NAME,
        user: process.env.DATABASE_USER,
        password: process.env.DATABASE_PASSWORD
    })
    await client.connect()
    try {
        const found = await client.query('SELECT credential FROM "user" WHERE email = $1', [email])
        if (found.rowCount === 0) {
            console.log('OK')
            return
        }
        const stored = found.rows[0].credential
        if (stored && bcrypt.compareSync(password, stored)) {
            console.log('OK')
            return
        }
        const hash = bcrypt.hashSync(password, bcrypt.genSaltSync(rounds))
        await client.query('UPDATE "user" SET credential = $1 WHERE email = $2', [hash, email])
        console.log('CHANGED')
    } finally {
        await client.end()
    }
}

main().catch((error) => fail(error.message))
