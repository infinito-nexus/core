<?php

/**
 * Admit a SAML sign-in only for members of a declared role group, and write the admin flag and the
 * profile columns of the SuiteCRM user from the assertion at every sign-in.
 *
 * Env of the container, from templates/env.j2:
 *   SUITECRM_SAML_GROUP_ATTRIBUTE        assertion attribute that lists the group paths
 *   SUITECRM_SAML_LOGIN_GROUPS           JSON list of the group paths whose members may sign in
 *   SUITECRM_SAML_ADMINISTRATOR_GROUPS   JSON list of the group paths whose members hold the admin flag
 *   SUITECRM_SAML_PROTECTED_USERS        JSON list of the usernames that sign in and keep their admin flag regardless of groups
 *   SUITECRM_SAML_PROFILE_COLUMNS        JSON object: assertion attribute => {"column": users column, "length": maximum characters}
 */

declare(strict_types=1);

namespace App\Extension\Iam\backend\Security;

use Doctrine\DBAL\Connection;
use InvalidArgumentException;
use Nbgrp\OneloginSamlBundle\Security\Http\Authenticator\Passport\Badge\SamlAttributesBadge;
use Symfony\Component\DependencyInjection\Attribute\Autowire;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;
use Symfony\Component\Security\Core\Exception\CustomUserMessageAuthenticationException;
use Symfony\Component\Security\Http\Authenticator\Passport\Badge\UserBadge;
use Symfony\Component\Security\Http\Authenticator\Passport\Passport;
use Symfony\Component\Security\Http\Event\CheckPassportEvent;
use Symfony\Component\Security\Http\Event\LoginSuccessEvent;

final class SamlDirectorySync implements EventSubscriberInterface
{
    private const COLUMN = '/^[a-z][a-z0-9_]*$/';

    private array $loginGroups;

    private array $administratorGroups;

    private array $protectedUsers;

    private array $profileColumns = [];

    public function __construct(
        private readonly Connection $connection,
        #[Autowire(env: 'SUITECRM_SAML_GROUP_ATTRIBUTE')] private readonly string $groupAttribute,
        #[Autowire(env: 'json:SUITECRM_SAML_LOGIN_GROUPS')] array $loginGroups,
        #[Autowire(env: 'json:SUITECRM_SAML_ADMINISTRATOR_GROUPS')] array $administratorGroups,
        #[Autowire(env: 'json:SUITECRM_SAML_PROTECTED_USERS')] array $protectedUsers,
        #[Autowire(env: 'json:SUITECRM_SAML_PROFILE_COLUMNS')] array $profileColumns,
    ) {
        $this->loginGroups = self::strings($loginGroups);
        $this->administratorGroups = self::strings($administratorGroups);
        $this->protectedUsers = array_map('strtolower', self::strings($protectedUsers));

        if ($this->groupAttribute === '' || $this->loginGroups === [] || $this->protectedUsers === []) {
            throw new InvalidArgumentException('SUITECRM_SAML_GROUP_ATTRIBUTE, SUITECRM_SAML_LOGIN_GROUPS and SUITECRM_SAML_PROTECTED_USERS must not be empty');
        }

        foreach ($profileColumns as $attribute => $target) {
            $column = is_array($target) ? ($target['column'] ?? null) : null;
            $length = is_array($target) ? ($target['length'] ?? null) : null;
            if (!is_string($attribute) || !is_string($column) || preg_match(self::COLUMN, $column) !== 1 || !is_int($length) || $length < 1) {
                throw new InvalidArgumentException("SUITECRM_SAML_PROFILE_COLUMNS holds an invalid entry for {$attribute}");
            }
            $this->profileColumns[$attribute] = ['column' => $column, 'length' => $length];
        }
    }

    public static function getSubscribedEvents(): array
    {
        return [
            CheckPassportEvent::class => ['onCheckPassport', 512],
            LoginSuccessEvent::class => ['onLoginSuccess', 16],
        ];
    }

    public function onCheckPassport(CheckPassportEvent $event): void
    {
        $passport = $event->getPassport();
        $attributes = self::samlAttributes($passport);
        if ($attributes === null) {
            return;
        }

        $username = self::username($passport);
        if ($this->isProtected($username)) {
            return;
        }

        if (array_intersect($this->groups($attributes), $this->loginGroups) === []) {
            $this->writeAdministrator($username, false);
            throw new CustomUserMessageAuthenticationException('Authentication: no role group of this application');
        }
    }

    public function onLoginSuccess(LoginSuccessEvent $event): void
    {
        $passport = $event->getPassport();
        $attributes = self::samlAttributes($passport);
        if ($attributes === null) {
            return;
        }

        $username = self::username($passport);
        $this->writeProfile($username, $attributes);

        if (!$this->isProtected($username)) {
            $this->writeAdministrator($username, array_intersect($this->groups($attributes), $this->administratorGroups) !== []);
        }
    }

    private function isProtected(string $username): bool
    {
        return in_array($username, $this->protectedUsers, true);
    }

    /**
     * @return string[]
     */
    private function groups(array $attributes): array
    {
        return self::strings($attributes[$this->groupAttribute] ?? []);
    }

    private function writeAdministrator(string $username, bool $administrator): void
    {
        if ($username === '') {
            return;
        }

        $flag = $administrator ? 1 : 0;
        $this->connection->executeStatement(
            'UPDATE users SET is_admin = ? WHERE deleted = 0 AND is_admin <> ? AND LOWER(user_name) = ?',
            [$flag, $flag, $username]
        );
    }

    private function writeProfile(string $username, array $attributes): void
    {
        $assignments = [];
        $values = [];
        foreach ($this->profileColumns as $attribute => $target) {
            $value = self::strings($attributes[$attribute] ?? [])[0] ?? null;
            if ($value === null) {
                continue;
            }
            $assignments[] = $target['column'] . ' = ?';
            $values[] = mb_substr($value, 0, $target['length']);
        }

        if ($username === '' || $assignments === []) {
            return;
        }

        $values[] = $username;
        $this->connection->executeStatement(
            'UPDATE users SET ' . implode(', ', $assignments) . ' WHERE deleted = 0 AND LOWER(user_name) = ?',
            $values
        );
    }

    private static function samlAttributes(Passport $passport): ?array
    {
        $badge = $passport->getBadge(SamlAttributesBadge::class);

        return $badge instanceof SamlAttributesBadge ? $badge->getAttributes() : null;
    }

    private static function username(Passport $passport): string
    {
        $badge = $passport->getBadge(UserBadge::class);

        return $badge instanceof UserBadge ? strtolower($badge->getUserIdentifier()) : '';
    }

    /**
     * @return string[]
     */
    private static function strings(mixed $value): array
    {
        if (is_string($value)) {
            return $value === '' ? [] : [$value];
        }

        if (!is_array($value)) {
            return [];
        }

        return array_values(array_filter($value, static fn ($item): bool => is_string($item) && $item !== ''));
    }
}
