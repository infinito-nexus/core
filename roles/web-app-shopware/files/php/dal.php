<?php
/**
 * The closing tag below hands over to the opening tag of the job script piped
 * after this file (files/php/oidc/client.php, files/php/design/showcase.php).
 *
 * Required env, supplied by the calling task via `container exec -e KEY` or by the container:
 *   SHOPWARE_ROOT  Shopware project directory holding vendor/autoload.php
 *   APP_ENV        kernel environment the container runs
 *   APP_DEBUG      optional kernel debug flag; unset means debug outside "prod", as bin/console derives it
 */

declare(strict_types=1);

function env(string $key): string
{
    $value = getenv($key);
    if ($value === false || $value === '') {
        fwrite(STDERR, "missing env {$key}\n");
        exit(1);
    }

    return $value;
}

/**
 * @param string $step what the call does, named in the failure line
 * @param callable(): mixed $call the Shopware call
 * @return mixed what the call returns; a throwable ends the script with exit 1
 *         after its class and message, and those of every previous one, reach
 *         STDERR with the value of every *SECRET* and *PASSWORD* env masked
 */
function guarded(string $step, callable $call): mixed
{
    try {
        return $call();
    } catch (Throwable $throwable) {
        $secrets = array_filter(
            getenv(),
            static fn (string $value, int|string $key): bool => $value !== '' && preg_match('/SECRET|PASSWORD/i', (string) $key) === 1,
            ARRAY_FILTER_USE_BOTH
        );
        for ($line = "{$step} failed"; $throwable !== null; $throwable = $throwable->getPrevious()) {
            $line .= sprintf("\n  %s: %s", $throwable::class, $throwable->getMessage());
        }
        fwrite(STDERR, str_replace(array_values($secrets), '***', $line) . "\n");
        exit(1);
    }
}

/**
 * @return Symfony\Component\DependencyInjection\ContainerInterface the container of the booted Shopware kernel
 */
function container(): Symfony\Component\DependencyInjection\ContainerInterface
{
    static $container = null;

    if ($container === null) {
        $container = guarded('boot the Shopware kernel', static function (): Symfony\Component\DependencyInjection\ContainerInterface {
            $root = env('SHOPWARE_ROOT');
            $classLoader = require "{$root}/vendor/autoload.php";
            if (is_file("{$root}/.env")) {
                (new Symfony\Component\Dotenv\Dotenv())->usePutenv()->bootEnv("{$root}/.env");
            }
            $environment = env('APP_ENV');
            $debug = isset($_SERVER['APP_DEBUG']) ? filter_var($_SERVER['APP_DEBUG'], FILTER_VALIDATE_BOOL) : $environment !== 'prod';
            $kernel = Shopware\Core\Framework\Adapter\Kernel\KernelFactory::create($environment, $debug, $classLoader);
            $kernel->boot();

            return $kernel->getContainer();
        });
    }

    return $container;
}

/**
 * @param string $operation "search", "create", "update", "upsert" or "delete"
 * @param string $entity the DAL entity name
 * @param array<string, mixed> $argument search: field => value equality filters; create, update and upsert: one payload;
 *        delete: ['id' => <id>]
 * @return list<array<string, mixed>> search: the matching rows, oldest first; every write: []
 */
function dal(string $operation, string $entity, array $argument): array
{
    return guarded("{$operation} {$entity}", static function () use ($operation, $entity, $argument): array {
        $repository = container()->get("{$entity}.repository");
        $context = Shopware\Core\Framework\Context::createCLIContext();

        if ($operation !== 'search') {
            match ($operation) {
                'create' => $repository->create([$argument], $context),
                'update' => $repository->update([$argument], $context),
                'upsert' => $repository->upsert([$argument], $context),
                'delete' => $repository->delete([$argument], $context),
            };

            return [];
        }

        $criteria = new Shopware\Core\Framework\DataAbstractionLayer\Search\Criteria();
        foreach ($argument as $field => $value) {
            $criteria->addFilter(new Shopware\Core\Framework\DataAbstractionLayer\Search\Filter\EqualsFilter($field, $value));
        }
        $criteria->addSorting(
            new Shopware\Core\Framework\DataAbstractionLayer\Search\Sorting\FieldSorting('createdAt'),
            new Shopware\Core\Framework\DataAbstractionLayer\Search\Sorting\FieldSorting('id')
        );

        return array_values(array_map(
            static fn (object $row): array => json_decode(json_encode($row, JSON_THROW_ON_ERROR), true, 512, JSON_THROW_ON_ERROR),
            $repository->search($criteria, $context)->getElements()
        ));
    });
}
?>
