use strict;
use warnings;

# Param PROXMOX_WORKSPACE_ACTION: apply or destroy.
# Param PROXMOX_WORKSPACE_ID: the workspace id; its pool and user are ws-<id> and ws-<id>@pve.
# Param PROXMOX_WORKSPACE_TOKEN_NAME: name of the user's privilege-separated token.
# Param PROXMOX_WORKSPACE_ROLES: JSON object of role name to privilege list, converged before apply grants them.
# Param PROXMOX_WORKSPACE_ACLS: JSON list of {path, role, propagate} the user and its token hold, and nothing else.
# Param PROXMOX_WORKSPACE_ISSUED: 1 when OpenBao holds the issued token, 0 to issue the token anew.
# Output: one "[CHANGED] ..." line per write and, as the last line, one JSON object {workspace, token, secret}; secret is null unless apply issued the token.

use JSON::PP qw(decode_json encode_json);
use PVE::RPCEnvironment;
use PVE::Cluster qw(cfs_read_file);
use PVE::AccessControl;
use PVE::API2::Role;
use PVE::API2::Pool;
use PVE::API2::User;
use PVE::API2::ACL;

sub required_env {
    my ($name) = @_;
    my $value = $ENV{$name} // '';
    die "[FAIL] $name arrived empty\n" if $value eq '';
    return $value;
}

my $action = required_env('PROXMOX_WORKSPACE_ACTION');
my $id = required_env('PROXMOX_WORKSPACE_ID');
my $token = required_env('PROXMOX_WORKSPACE_TOKEN_NAME');
die "[FAIL] workspace id $id is no lowercase UUID\n"
    if $id !~ /\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z/;
die "[FAIL] action $action is neither apply nor destroy\n"
    if $action ne 'apply' && $action ne 'destroy';

my $pool = "ws-$id";
my $user = "ws-$id\@pve";
my $full = "$user!$token";

PVE::RPCEnvironment->setup_default_cli_env();
my $usercfg = cfs_read_file('user.cfg');

sub held_acls {
    my @held;
    my @queue = (['', $usercfg->{acl_root} // {}]);
    while (my $entry = shift @queue) {
        my ($path, $node) = @$entry;
        for my $kind (['users', $user], ['tokens', $full]) {
            my $roles = (($node->{$kind->[0]} // {})->{$kind->[1]}) // {};
            push @held, { path => ($path eq '' ? '/' : $path), kind => $kind->[0], role => $_ } for sort keys %$roles;
        }
        my $children = $node->{children} // {};
        push @queue, ["$path/$_", $children->{$_}] for sort keys %$children;
    }
    return @held;
}

sub grant {
    my ($kind, %acl) = @_;
    PVE::API2::ACL->update_acl({
        path => $acl{path},
        roles => $acl{role},
        ($kind eq 'users' ? (users => $user) : (tokens => $full)),
        %acl{grep { exists $acl{$_} } qw(propagate delete)},
    });
}

sub apply {
    my $roles = decode_json(required_env('PROXMOX_WORKSPACE_ROLES'));
    my $acls = decode_json(required_env('PROXMOX_WORKSPACE_ACLS'));
    my $stored = required_env('PROXMOX_WORKSPACE_ISSUED');

    for my $role (sort keys %$roles) {
        my $want = join(',', sort @{ $roles->{$role} });
        my $have = ($usercfg->{roles} // {})->{$role};
        if (!$have) {
            PVE::API2::Role->create_role({ roleid => $role, privs => $want });
            print "[CHANGED] role $role created\n";
        } elsif (join(',', sort keys %$have) ne $want) {
            PVE::API2::Role->update_role({ roleid => $role, privs => $want });
            print "[CHANGED] role $role privileges set\n";
        }
    }

    if (!($usercfg->{pools} // {})->{$pool}) {
        PVE::API2::Pool->create_pool({ poolid => $pool, comment => "Infinito.Nexus workspace $id" });
        print "[CHANGED] pool $pool created\n";
    }

    my $account = ($usercfg->{users} // {})->{$user};
    if (!$account) {
        PVE::API2::User->create_user({ userid => $user, enable => 1, comment => "Infinito.Nexus workspace $id" });
        print "[CHANGED] user $user created\n";
    }

    my $secret;
    my $issued = (($account // {})->{tokens} // {})->{$token};
    if ($issued && $stored ne '1') {
        PVE::API2::User->remove_token({ userid => $user, tokenid => $token });
        print "[CHANGED] token $full removed, OpenBao holds no secret of it\n";
        $issued = undef;
    }
    if (!$issued) {
        my $created = PVE::API2::User->generate_token({
            userid => $user,
            tokenid => $token,
            privsep => 1,
            comment => "Infinito.Nexus workspace $id provision",
        });
        $secret = ($created // {})->{value};
        die "[FAIL] Proxmox VE issued $full without a secret\n" if !defined $secret || $secret eq '';
        print "[CHANGED] token $full issued\n";
    }

    my %wanted;
    for my $acl (@$acls) {
        for my $kind (qw(users tokens)) {
            $wanted{"$kind $acl->{path} $acl->{role}"} = 1;
        }
    }
    my %held;
    for my $acl (held_acls()) {
        my $key = "$acl->{kind} $acl->{path} $acl->{role}";
        $held{$key} = 1;
        next if $wanted{$key};
        grant($acl->{kind}, path => $acl->{path}, role => $acl->{role}, delete => 1);
        print "[CHANGED] $acl->{role} on $acl->{path} revoked from $acl->{kind} of $pool\n";
    }
    for my $acl (@$acls) {
        for my $kind (qw(users tokens)) {
            next if $held{"$kind $acl->{path} $acl->{role}"};
            grant($kind, path => $acl->{path}, role => $acl->{role}, propagate => $acl->{propagate});
            print "[CHANGED] $acl->{role} on $acl->{path} granted to $kind of $pool\n";
        }
    }
    return $secret;
}

sub destroy {
    my $members = ((($usercfg->{pools} // {})->{$pool} // {})->{vms}) // {};
    die "[FAIL] pool $pool still holds the VMs " . join(', ', sort keys %$members)
        . "; destroy every server of the workspace first\n"
        if %$members;
    for my $acl (held_acls()) {
        grant($acl->{kind}, path => $acl->{path}, role => $acl->{role}, delete => 1);
        print "[CHANGED] $acl->{role} on $acl->{path} revoked from $acl->{kind} of $pool\n";
    }
    my $account = ($usercfg->{users} // {})->{$user};
    if ((($account // {})->{tokens} // {})->{$token}) {
        PVE::API2::User->remove_token({ userid => $user, tokenid => $token });
        print "[CHANGED] token $full removed\n";
    }
    if ($account) {
        PVE::API2::User->delete_user({ userid => $user });
        print "[CHANGED] user $user removed\n";
    }
    if (($usercfg->{pools} // {})->{$pool}) {
        PVE::API2::Pool->delete_pool({ poolid => $pool });
        print "[CHANGED] pool $pool removed\n";
    }
    return undef;
}

my $secret = $action eq 'apply' ? apply() : destroy();
print encode_json({ workspace => $id, token => $full, secret => $secret }), "\n";
