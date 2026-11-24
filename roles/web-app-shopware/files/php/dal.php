<?php
// nocheck: mirrored-unit-test - boots Shopware's kernel from vendor/autoload.php, which only exists inside the web container;
// tests/unit/php/roles/web-app-shopware/files/oidc/ClientTest.php and files/design/ShowcaseTest.php run this file with stubs in place of container() and dal()
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
 * @return Symfony\Component\DependencyInjection\ContainerInterface the container of the booted Shopware kernel
 */
function container(): Symfony\Component\DependencyInjection\ContainerInterface
{
    static $container = null;

    if ($container === null) {
        $root = env('SHOPWARE_ROOT');
        $classLoader = require "{$root}/vendor/autoload.php";
        if (is_file("{$root}/.env")) {
            (new Symfony\Component\Dotenv\Dotenv())->usePutenv()->bootEnv("{$root}/.env");
        }
        $environment = env('APP_ENV');
        $debug = isset($_SERVER['APP_DEBUG']) ? filter_var($_SERVER['APP_DEBUG'], FILTER_VALIDATE_BOOL) : $environment !== 'prod';
        $kernel = Shopware\Core\Framework\Adapter\Kernel\KernelFactory::create($environment, $debug, $classLoader);
        $kernel->boot();
        $container = $kernel->getContainer();
    }

    return $container;
}

/**
 * @param string $operation "search", "upsert" or "delete"
 * @param string $entity the DAL entity name
 * @param array<string, mixed> $argument search: field => value equality filters; upsert: one payload; delete: ['id' => <id>]
 * @return list<array<string, mixed>> search: the matching rows, oldest first; upsert and delete: []
 */
function dal(string $operation, string $entity, array $argument): array
{
    $repository = container()->get("{$entity}.repository");
    $context = Shopware\Core\Framework\Context::createCLIContext();

    if ($operation === 'upsert') {
        $repository->upsert([$argument], $context);

        return [];
    }

    if ($operation === 'delete') {
        $repository->delete([$argument], $context);

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
}
?>
