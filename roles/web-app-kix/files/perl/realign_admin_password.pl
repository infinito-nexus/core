#!/usr/bin/perl
# Param env KIX_HOME: install root the ObjectManager reads EXPORTS from; the image exports it in the entrypoint's shell only, and for a program on STDIN its FindBin fallback resolves to the working directory instead, so every `container exec` must hand it over
# Param env KIX_REALIGN_LOGIN: login of the account the deployment declares
# Param env KIX_REALIGN_PASSWORD: password that login must accept afterwards, handed over with `container exec -e <name>` so it reaches no argument list
# Param env KIX_REALIGN_USAGE_CONTEXT: usage context the account signs in with
# Output: [UNCHANGED] when the account already accepts the password, [CHANGED] when it was written, [FAIL] on stderr with exit 1 otherwise

use strict;
use warnings;

use Kernel::System::ObjectManager;

sub Fail {
    my ($Message) = @_;
    print STDERR "[FAIL] $Message\n";
    exit 1;
}

my $Login        = $ENV{KIX_REALIGN_LOGIN}         || '';
my $Password     = $ENV{KIX_REALIGN_PASSWORD}      || '';
my $UsageContext = $ENV{KIX_REALIGN_USAGE_CONTEXT} || '';

Fail('KIX_REALIGN_LOGIN, KIX_REALIGN_PASSWORD and KIX_REALIGN_USAGE_CONTEXT must all carry a value')
    if !length $Login || !length $Password || !length $UsageContext;

local $Kernel::OM = Kernel::System::ObjectManager->new(
    'Log' => { LogPrefix => 'infinito-realign-admin-password' },
);

my $UserObject = $Kernel::OM->Get('Kernel::System::User');
my $UserID     = $UserObject->UserLookup( UserLogin => $Login, Silent => 1 );

Fail("there is no account named '$Login'") if !$UserID;

# A probe this KIX cannot answer must fall through to the write: it only decides whether one is needed.
my $Accepted = eval {
    $Kernel::OM->Get('Kernel::System::Auth')->Auth(
        User         => $Login,
        Pw           => $Password,
        UsageContext => $UsageContext,
    );
};

if ($Accepted) {
    print "[UNCHANGED] '$Login' already accepts the declared password\n";
    exit 0;
}

Fail("the password of '$Login' could not be written")
    if !$UserObject->SetPassword( UserLogin => $Login, PW => $Password );

# KIX counted the probe above as a failed login, and escalates a run of those into a temporary lockout.
eval { $UserObject->SetPreferences( Key => 'UserLoginFailed', Value => 0, UserID => $UserID ) };

print "[CHANGED] '$Login' was realigned with the declared password\n";
