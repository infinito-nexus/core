use strict;
use warnings;

# Param PROXMOX_REALM: id of the OpenID Connect realm.
# Param PROXMOX_REALM_CONFIG: JSON object of the realm options except the client secret.
# Param PROXMOX_REALM_CLIENT_SECRET_B64: base64 of the client secret; the deploy exports it from stdin, so it never reaches an argv.
# Param PROXMOX_GROUP: group that receives PROXMOX_ROLE on "/".
# Param PROXMOX_GROUP_COMMENT: comment of that group.
# Param PROXMOX_ROLE: built-in role granted to the group.
# Output: one "[CHANGED] ..." line per write, naming option keys but never a value.

use JSON::PP qw(decode_json);
use MIME::Base64 qw(decode_base64);
use PVE::RPCEnvironment;
use PVE::Cluster qw(cfs_read_file);
use PVE::AccessControl;
use PVE::API2::Domains;
use PVE::API2::Group;
use PVE::API2::ACL;

sub required_env {
    my ($name) = @_;
    my $value = $ENV{$name} // '';
    die "[FAIL] $name arrived empty\n" if $value eq '';
    return $value;
}

my $realm = required_env('PROXMOX_REALM');
my $group = required_env('PROXMOX_GROUP');
my $group_comment = required_env('PROXMOX_GROUP_COMMENT');
my $role = required_env('PROXMOX_ROLE');
my $desired = decode_json(required_env('PROXMOX_REALM_CONFIG'));
$desired->{'client-key'} = decode_base64(required_env('PROXMOX_REALM_CLIENT_SECRET_B64'));
die "[FAIL] the client secret decoded to an empty string\n" if $desired->{'client-key'} eq '';

PVE::RPCEnvironment->setup_default_cli_env();

my $current = cfs_read_file('domains.cfg')->{ids}->{$realm};
if (!$current) {
    PVE::API2::Domains->create({ realm => $realm, type => 'openid', %$desired });
    print "[CHANGED] realm $realm created\n";
} else {
    die "[FAIL] realm $realm has type $current->{type}, not openid\n"
        if $current->{type} ne 'openid';
    my $claim = $desired->{'username-claim'};
    my $current_claim = $current->{'username-claim'} // 'sub';
    die "[FAIL] realm $realm maps users by the claim '$current_claim', not '$claim'; "
        . "Proxmox VE fixes that claim when the realm is created, so delete the realm "
        . "inside the container (pveum realm delete $realm) and redeploy\n"
        if $current_claim ne $claim;
    my @stale = grep { $_ ne 'username-claim' && ($current->{$_} // '') ne $desired->{$_} }
        sort keys %$desired;
    if (@stale) {
        PVE::API2::Domains->update({ realm => $realm, map { ($_ => $desired->{$_}) } @stale });
        print "[CHANGED] realm $realm updated: " . join(', ', @stale) . "\n";
    }
}

my $usercfg = cfs_read_file('user.cfg');
my $existing = $usercfg->{groups}->{$group};
if (!$existing) {
    PVE::API2::Group->create_group({ groupid => $group, comment => $group_comment });
    print "[CHANGED] group $group created\n";
} elsif (($existing->{comment} // '') ne $group_comment) {
    PVE::API2::Group->update_group({ groupid => $group, comment => $group_comment });
    print "[CHANGED] group $group comment updated\n";
}

my $granted = (($usercfg->{acl_root} // {})->{groups} // {})->{$group} // {};
if (!$granted->{$role}) {
    PVE::API2::ACL->update_acl({ path => '/', groups => $group, roles => $role, propagate => 1 });
    print "[CHANGED] role $role granted to group $group on /\n";
}
