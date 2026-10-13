<?php
// nocheck: mirrored-unit-test - a MediaWiki maintenance script loaded by maintenance/run.php against the live wiki database; nothing here runs outside a booted MediaWiki

use MediaWiki\Maintenance\Maintenance;

/**
 * Args:
 *   MW_ADMIN_NAME (env): username of the platform administrator.
 *   MW_ADMIN_PASSWORD (env): password to converge on that account.
 *
 * Output:
 *   One line "created", "changed" or "unchanged" on stdout.
 */
class ConvergeAdmin extends Maintenance {
	public function execute() {
		$name = getenv( 'MW_ADMIN_NAME' );
		$password = getenv( 'MW_ADMIN_PASSWORD' );
		if ( !$name || !$password ) {
			$this->fatalError( 'MW_ADMIN_NAME and MW_ADMIN_PASSWORD are required' );
		}
		$services = $this->getServiceContainer();
		$user = $services->getUserFactory()->newFromName( $name );
		if ( !$user ) {
			$this->fatalError( 'MW_ADMIN_NAME is not a valid username' );
		}
		$state = 'unchanged';
		if ( $user->idForName() === 0 ) {
			$user->addToDatabase();
			$state = 'created';
		}
		$groups = $services->getUserGroupManager();
		foreach ( [ 'sysop', 'bureaucrat' ] as $group ) {
			if ( !in_array( $group, $groups->getUserGroups( $user ), true ) ) {
				$groups->addUserToGroup( $user, $group );
				$state = $state === 'created' ? 'created' : 'changed';
			}
		}
		$hash = $services->getConnectionProvider()->getPrimaryDatabase()
			->newSelectQueryBuilder()
			->select( 'user_password' )
			->from( 'user' )
			->where( [ 'user_id' => $user->getId() ] )
			->caller( __METHOD__ )
			->fetchField();
		if ( !$services->getPasswordFactory()->newFromCiphertext( $hash ?: null )->verify( $password ) ) {
			$status = $user->changeAuthenticationData( [
				'username' => $user->getName(),
				'password' => $password,
				'retype' => $password,
			] );
			if ( !$status->isGood() ) {
				$this->fatalError( $status );
			}
			$state = $state === 'created' ? 'created' : 'changed';
		}
		$this->output( "$state\n" );
	}
}

$maintClass = ConvergeAdmin::class;
