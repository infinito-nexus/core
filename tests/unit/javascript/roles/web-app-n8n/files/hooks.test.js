const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')
const Module = require('node:module')

const { ready } = require(path.resolve(__dirname, '../../../../../../roles/web-app-n8n/files/javascript/hooks.js')).n8n

const N8N = '/stub/n8n/dist/index.js'
const EXPRESS = '/stub/express/index.js'
const LOGGER = Symbol('Logger')
const AUTH_IDENTITIES = Symbol('AuthIdentityRepository')
const HEADER = 'Remote-Email'
const ALICE = 'alice@example.org'

class Layer {
    constructor(_route, _options, handle) {
        this.handle = handle
    }
}

function accessToken(claims) {
    return ['header', Buffer.from(JSON.stringify(claims)).toString('base64'), 'signature'].join('.')
}

function matches(record, where) {
    return Object.entries(where).every(([key, value]) =>
        key === 'role' ? record.role?.slug === value.slug : record[key] === value
    )
}

/**
 * @param {object[]} accounts the n8n users.
 * @param {object[]} identities the auth_identity rows.
 * Returns: the response, the next() calls and the users the SSO middleware of
 * hooks.js created, linked and issued a session cookie for one request.
 */
async function signIn(accounts, identities) {
    const effects = { created: [], linked: [], cookies: [] }
    const users = {
        findOne: async ({ where }) => accounts.find((account) => matches(account, where)) || null,
        createUserWithProject: async (data) => {
            effects.created.push(data.email)
            return { user: { id: 'u-new', ...data } }
        },
        save: async () => {}
    }
    const authIdentities = {
        findOne: async ({ where }) => identities.find((identity) => matches(identity, where)) || null,
        create: (row) => row,
        save: async (row) => {
            effects.linked.push(row)
        }
    }
    const services = new Map([
        [LOGGER, { info() {}, debug() {}, error() {} }],
        [AUTH_IDENTITIES, authIdentities]
    ])
    const modules = {
        '@n8n/di': { Container: { get: (token) => services.get(token) } },
        '@n8n/backend-common': { Logger: LOGGER },
        '@n8n/db': { AuthIdentityRepository: AUTH_IDENTITIES },
        bcryptjs: { hash: async () => 'hashed' },
        'router/lib/layer': Layer,
        [path.resolve(path.dirname(N8N), 'auth/jwt')]: {
            issueCookie: (_res, user) => effects.cookies.push(user.id)
        }
    }
    const resolved = { n8n: N8N, express: EXPRESS }
    const stack = [{ name: 'cookieParser' }]
    const load = Module._load
    const resolveFilename = Module._resolveFilename
    Module._load = function (request, ...rest) {
        return Object.hasOwn(modules, request) ? modules[request] : load.call(this, request, ...rest)
    }
    Module._resolveFilename = function (request, ...rest) {
        return Object.hasOwn(resolved, request) ? resolved[request] : resolveFilename.call(this, request, ...rest)
    }
    process.env.N8N_FORWARD_AUTH_HEADER = HEADER
    process.env.N8N_SSO_OWNER_USERNAME = 'administrator'
    try {
        await ready[0].call(
            { dbCollections: { User: users } },
            { app: { set() {}, router: { stack } } },
            { get: () => true }
        )
    } finally {
        Module._load = load
        Module._resolveFilename = resolveFilename
    }
    const res = { statusCode: undefined, end(body) { this.body = body } }
    const nexts = []
    await stack[1].handle(
        {
            url: '/home/workflows',
            cookies: {},
            headers: {
                [HEADER.toLowerCase()]: ALICE,
                'x-forwarded-preferred-username': 'alice',
                'x-forwarded-access-token': accessToken({ sub: 'kc-alice', email_verified: true })
            }
        },
        res,
        (...args) => nexts.push(args)
    )
    return { res, nexts, ...effects }
}

test('an email address another n8n account holds is refused with 409 and links nothing', async () => {
    const result = await signIn([{ id: 'u-bob', email: ALICE, role: { slug: 'global:member' } }], [])
    assert.equal(result.res.statusCode, 409)
    assert.deepEqual([result.nexts, result.created, result.linked, result.cookies], [[], [], [], []])
})

test('a free email address provisions and links a new account', async () => {
    const result = await signIn([], [])
    assert.equal(result.res.statusCode, undefined)
    assert.deepEqual(result.nexts, [[]])
    assert.deepEqual(result.created, [ALICE])
    assert.deepEqual(result.linked, [{ userId: 'u-new', providerId: 'kc-alice', providerType: 'oidc' }])
    assert.deepEqual(result.cookies, ['u-new'])
})

test('the account bound to the subject signs in although another account holds the address', async () => {
    const result = await signIn(
        [
            { id: 'u-bob', email: ALICE, role: { slug: 'global:member' } },
            { id: 'u-alice', email: 'alice@old.example.org', role: { slug: 'global:member' } }
        ],
        [{ userId: 'u-alice', providerId: 'kc-alice', providerType: 'oidc' }]
    )
    assert.equal(result.res.statusCode, undefined)
    assert.deepEqual([result.created, result.linked, result.cookies], [[], [], ['u-alice']])
})
