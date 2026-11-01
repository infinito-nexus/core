const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const { plan } = require(path.resolve(__dirname, '../../../../../../../roles/web-app-n8n/files/javascript/reconcile/sso_identities.js'))

const ALICE = { username: 'alice', email: 'Alice@Example.org', emailVerified: true, id: 'kc-alice' }

function account(overrides = {}) {
    return { id: 'u-alice', email: 'alice@example.org', roleSlug: 'global:member', subjects: [], ...overrides }
}

test('an unlinked account whose email matches a verified Keycloak user is bound to its subject', () => {
    assert.deepEqual(plan([ALICE], [account()], new Map()), {
        bind: [{ userId: 'u-alice', subject: 'kc-alice' }],
        skipped: []
    })
})

test('an unverified Keycloak email is skipped by username, never by address', () => {
    const result = plan([{ ...ALICE, emailVerified: false }], [account()], new Map())
    assert.deepEqual(result, { bind: [], skipped: [{ username: 'alice', reason: 'the Keycloak email is not verified' }] })
    assert.doesNotMatch(JSON.stringify(result.skipped), /@/)
})

test('an account linked to another subject is never rebound', () => {
    assert.deepEqual(plan([ALICE], [account({ subjects: ['kc-other'] })], new Map([['kc-other', 'u-alice']])), {
        bind: [],
        skipped: [{ username: 'alice', reason: 'the account is linked to another identity' }]
    })
})

test('a subject another account holds is never moved', () => {
    assert.deepEqual(plan([ALICE], [account()], new Map([['kc-alice', 'u-bob']])), {
        bind: [],
        skipped: [{ username: 'alice', reason: 'the identity is linked to another account' }]
    })
})

test('the instance owner is left to the username mapping of hooks.js', () => {
    assert.deepEqual(plan([ALICE], [account({ roleSlug: 'global:owner' })], new Map()), { bind: [], skipped: [] })
})

test('an account already bound to its subject is left alone', () => {
    assert.deepEqual(plan([ALICE], [account({ subjects: ['kc-alice'] })], new Map([['kc-alice', 'u-alice']])), {
        bind: [],
        skipped: []
    })
})

test('a Keycloak user without an n8n account creates nothing', () => {
    assert.deepEqual(plan([ALICE], [], new Map()), { bind: [], skipped: [] })
})
