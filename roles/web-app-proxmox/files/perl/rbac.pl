use strict;
use warnings;

# Param PROXMOX_REALM: id of the OpenID Connect realm the members sign in through.
# Param PROXMOX_GROUP: group that holds the administrator role; files/perl/access.pl creates it.
# Param PROXMOX_RBAC_ADMINISTRATORS: JSON list of {username, email, name} of the administrator role group.
# Output: one "[CHANGED] ..." line per promoted or demoted account.

use JSON::PP qw(decode_json);
use PVE::RPCEnvironment;
use PVE::Cluster qw(cfs_read_file);
use PVE::AccessControl;
use PVE::API2::User;

sub required_env {
    my ($name) = @_;
    my $value = $ENV{$name} // '';
    die "[FAIL] $name arrived empty\n" if $value eq '';
    return $value;
}

my $realm = required_env('PROXMOX_REALM');
my $group = required_env('PROXMOX_GROUP');
my $members = decode_json(required_env('PROXMOX_RBAC_ADMINISTRATORS'));

PVE::RPCEnvironment->setup_default_cli_env();

my $usercfg = cfs_read_file('user.cfg');
my $groups = $usercfg->{groups} // {};
die "[FAIL] group $group does not exist; a deploy of web-app-proxmox creates it\n"
    if !$groups->{$group};
my $holders = $groups->{$group}->{users} // {};

my %wanted = map { ("$_->{username}\@$realm" => $_) } grep { ($_->{username} // '') ne '' } @$members;

for my $userid (sort keys %wanted) {
    next if $holders->{$userid};
    if (!($usercfg->{users} // {})->{$userid}) {
        my $email = $wanted{$userid}->{email} // '';
        PVE::API2::User->create_user({
            userid => $userid,
            enable => 1,
            groups => $group,
            ($email ne '' ? (email => $email) : ()),
        });
        print "[CHANGED] $userid created in group $group\n";
        next;
    }
    PVE::API2::User->update_user({ userid => $userid, groups => $group, append => 1 });
    print "[CHANGED] $userid added to group $group\n";
}

for my $userid (sort keys %$holders) {
    next if $wanted{$userid};
    my @kept = sort grep { $_ ne $group && (($groups->{$_}->{users} // {})->{$userid}) } keys %$groups;
    PVE::API2::User->update_user({ userid => $userid, groups => join(',', @kept) });
    print "[CHANGED] $userid removed from group $group\n";
}
