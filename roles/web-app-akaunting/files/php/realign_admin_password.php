// Tinker snippet, not a standalone script: it is passed to `artisan tinker --execute`,
// which evaluates PHP without an opening tag.
//
// Reads ADMIN_EMAIL and ADMIN_PASSWORD from the environment so neither reaches a
// command line. Prints CHANGED, UNCHANGED or FAILED.
//
// The password is assigned in clear text on purpose. User::setPasswordAttribute
// bcrypts it on save, so hashing here would store a hash of a hash.
$email = getenv('ADMIN_EMAIL');
$password = getenv('ADMIN_PASSWORD');
$user = $email ? \App\Models\Auth\User::where('email', $email)->first() : null;
if (!$email) {
    echo "FAILED: ADMIN_EMAIL is empty, so no account can be addressed\n";
} elseif (!$user) {
    echo "FAILED: no Akaunting account carries " . var_export($email, true)
        . "; an instance installed before the platform administrator split still holds"
        . " its only account under the previous address. Open Akaunting, change that"
        . " account's e-mail to this one, then deploy again.\n";
} elseif (\Illuminate\Support\Facades\Hash::check($password, (string) $user->password)) {
    echo "UNCHANGED\n";
} else {
    $user->password = $password;
    $user->save();
    echo "CHANGED\n";
}
