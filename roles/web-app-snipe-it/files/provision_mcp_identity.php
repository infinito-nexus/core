<?php
/**
 * Give the MCP adapter a read-only Snipe-IT user and print its access token.
 *
 * Passport signs its tokens, so the deployment cannot pin one. What it pins is
 * the user and its permission group; the token is captured from the mint that
 * follows and handed to the adapter through its env file.
 *
 * Snipe-IT's image never provisions Passport's keys or its personal-access
 * client, so createToken() would throw on a fresh deployment. Both are ensured
 * here before anything is minted.
 *
 * Prints CHANGED or UNCHANGED on the first line and the token on the second.
 *
 * Environment:
 *     MCP_USER:          username to converge.
 *     MCP_PASSWORD:      password to pin on it.
 *     MCP_TOKEN_NAME:    personal access token name to converge.
 *     MCP_CURRENT_TOKEN: token the adapter holds today, or "" for none.
 */

require "vendor/autoload.php";
$app = require "bootstrap/app.php";
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;

$username = getenv("MCP_USER");
$password = getenv("MCP_PASSWORD");
$tokenName = getenv("MCP_TOKEN_NAME");
$currentToken = trim((string) getenv("MCP_CURRENT_TOKEN"));

$permissions = json_encode([
    "self.api" => "1",
    "assets.view" => "1",
    "licenses.view" => "1",
]);

if ($currentToken !== "") {
    $probe = curl_init("http://127.0.0.1/api/v1/hardware?limit=1");
    curl_setopt_array($probe, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            "Authorization: Bearer " . $currentToken,
            "Accept: application/json",
        ],
        CURLOPT_TIMEOUT => 20,
    ]);
    curl_exec($probe);
    if (curl_getinfo($probe, CURLINFO_HTTP_CODE) === 200) {
        echo "UNCHANGED\n";
        echo $currentToken . "\n";
        exit(0);
    }
}

$changed = false;

if (!file_exists(storage_path("oauth-private.key"))) {
    Artisan::call("passport:keys", ["--no-interaction" => true]);
    $changed = true;
}

if (!DB::table("oauth_personal_access_clients")->exists()) {
    Artisan::call("passport:client", [
        "--personal" => true,
        "--name" => "Infinito personal access client",
        "--no-interaction" => true,
    ]);
    $changed = true;
}

$group = \App\Models\Group::where("name", "mcp-readonly")->first();
if (!$group) {
    $group = \App\Models\Group::create([
        "name" => "mcp-readonly",
        "permissions" => $permissions,
    ]);
    $changed = true;
} elseif ($group->permissions !== $permissions) {
    $group->permissions = $permissions;
    $group->save();
    $changed = true;
}

$user = \App\Models\User::where("username", $username)->whereNull("deleted_at")->first();
if (!$user) {
    $user = new \App\Models\User();
    $user->first_name = "MCP";
    $user->last_name = "Adapter";
    $user->username = $username;
    $user->activated = 1;
    $user->password = bcrypt($password);
    $user->save();
    $changed = true;
} elseif (!\Illuminate\Support\Facades\Hash::check($password, (string) $user->password)) {
    $user->password = bcrypt($password);
    $user->save();
    $changed = true;
}
$user->groups()->sync([$group->id]);

$revoked = DB::table("oauth_access_tokens")
    ->where("user_id", $user->id)
    ->where("name", $tokenName)
    ->where("revoked", 0)
    ->update(["revoked" => 1]);
$changed = $changed || $revoked > 0;

$token = $user->createToken($tokenName)->accessToken;

echo ($changed ? "CHANGED" : "UNCHANGED") . "\n";
echo $token . "\n";
