<?php

declare(strict_types=1);

namespace Espo\Entities {
    class User
    {
        public const TYPE_ADMIN = 'admin';
        public const TYPE_REGULAR = 'regular';
        public const TYPE_PORTAL = 'portal';
        public const TYPE_API = 'api';

        private array $values;
        private array $storedTeams = [];

        public function __construct(public string $userName, string $type)
        {
            $this->values = ['type' => $type];
        }

        /**
         * @param list<string> $teamIds ids of the teams the stored account belongs to
         */
        public function inTeams(array $teamIds): self
        {
            $this->storedTeams = $teamIds;

            return $this;
        }

        public function getUserName(): string
        {
            return $this->userName;
        }

        public function get(string $name): mixed
        {
            return $this->values[$name] ?? null;
        }

        public function set(string $name, mixed $value): void
        {
            $this->values[$name] = $value;
        }

        public function loadLinkMultipleField(string $link): void
        {
            $this->values[$link . 'Ids'] = $this->storedTeams;
        }

        public function getLinkMultipleIdList(string $link): array
        {
            if (!array_key_exists($link . 'Ids', $this->values)) {
                throw new \LogicException("{$link} read before it was loaded");
            }

            return $this->values[$link . 'Ids'];
        }

        public function isAdmin(): bool
        {
            return $this->get('type') === self::TYPE_ADMIN;
        }

        public function isRegular(): bool
        {
            return $this->get('type') === self::TYPE_REGULAR;
        }
    }
}

namespace Espo\Core\Utils {
    class Config
    {
        public function __construct(private array $values)
        {
        }

        public function get(string $name): mixed
        {
            return $this->values[$name] ?? null;
        }
    }

    class Log
    {
        public array $messages = [];
        public array $errors = [];

        public function info(string $message): void
        {
            $this->messages[] = $message;
        }

        public function error(string $message, array $context): void
        {
            $this->errors[] = [$message, $context];
        }
    }
}

namespace Espo\Core\Acl\Cache {
    use Espo\Entities\User;

    class Clearer
    {
        public array $cleared = [];

        public function clearForUser(User $user): void
        {
            $this->cleared[] = $user->userName;
        }
    }
}
