<?php
// nocheck: mirrored-unit-test - boots Magento through app/bootstrap.php and writes configuration rows,
// media files and a storefront theme through Magento's own services; top-level procedural code
/**
 * Required env:
 *   MAGENTO_DESIGN_ENABLED  "true" applies the design, anything else withdraws what an earlier run applied
 *   MAGENTO_DESIGN_VALUES   JSON object {"<config path>": "<value>"} for the default scope
 *   MAGENTO_DESIGN_FILES    JSON object {"<config path>": {"directory": "<media directory>", "source": "<file>"}};
 *                           the file is stored under a name that carries its hash and the path holds that name
 *   MAGENTO_DESIGN_THEME    JSON object {"path": "frontend/<Vendor>/<name>", "title", "parent": "<Vendor>/<name>",
 *                           "variables": {"<less variable>": "<value>"}}, or {} for no theme
 *
 * A row is written only while it is unset or still holds what an earlier run wrote.
 *
 * Stdout, one line each:
 *   locales: <locales of the store views, space separated>
 *   theme: none | current | stale (its compiled stylesheets are missing)
 *   changed | unchanged
 */

declare(strict_types=1);

use Magento\Framework\App\Area;
use Magento\Framework\App\Bootstrap;
use Magento\Framework\App\Cache\Manager as CacheManager;
use Magento\Framework\App\Config\ConfigResource\ConfigInterface as ConfigWriter;
use Magento\Framework\App\Config\ScopeConfigInterface;
use Magento\Framework\App\Filesystem\DirectoryList;
use Magento\Framework\App\ResourceConnection;
use Magento\Framework\App\State;
use Magento\Framework\Component\ComponentRegistrar;
use Magento\Framework\Filesystem;
use Magento\Framework\Indexer\IndexerRegistry;
use Magento\Store\Model\ScopeInterface;
use Magento\Store\Model\StoreManagerInterface;
use Magento\Theme\Model\Theme\Registration as ThemeRegistration;

const MARK = 'infinito/design/applied';
const THEME_ID = 'design/theme/theme_id';
const OWNED_NAME = 'infinito';

require_once '/var/www/html/app/bootstrap.php';

$objects ??= Bootstrap::create(BP, $_SERVER)->getObjectManager();
$objects->get(State::class)->setAreaCode(Area::AREA_ADMINHTML);

$resource = $objects->get(ResourceConnection::class);
$connection = $resource->getConnection();
$table = $resource->getTableName('core_config_data');
$writer = $objects->get(ConfigWriter::class);
$scopeConfig = $objects->get(ScopeConfigInterface::class);
$filesystem = $objects->get(Filesystem::class);
$media = $filesystem->getDirectoryWrite(DirectoryList::MEDIA);
$app = $filesystem->getDirectoryWrite(DirectoryList::APP);
$static = $filesystem->getDirectoryWrite(DirectoryList::STATIC_VIEW);
$var = $filesystem->getDirectoryWrite(DirectoryList::VAR_DIR);
$themeTable = $resource->getTableName('theme');

$stored = static function (string $path) use ($connection, $table): ?string {
    $value = $connection->fetchOne(
        $connection->select()->from($table, 'value')
            ->where('path = ?', $path)
            ->where('scope = ?', ScopeConfigInterface::SCOPE_TYPE_DEFAULT)
            ->where('scope_id = ?', 0)
    );

    return $value === false ? null : (string) $value;
};
$setting = static function (string $name): array {
    return json_decode((string) getenv($name), true, 8, JSON_THROW_ON_ERROR);
};
$themeWhere = static function (string $path): array {
    [$area, $name] = explode('/', $path, 2);

    return ['area = ?' => $area, 'theme_path = ?' => $name];
};

$enabled = getenv('MAGENTO_DESIGN_ENABLED') === 'true';
$wanted = $enabled ? $setting('MAGENTO_DESIGN_VALUES') : [];
$files = $enabled ? $setting('MAGENTO_DESIGN_FILES') : [];
$theme = $enabled ? $setting('MAGENTO_DESIGN_THEME') : [];
$applied = (json_decode($stored(MARK) ?? 'null', true) ?? []) + ['values' => [], 'files' => [], 'theme' => null];
$changed = false;

$locales = [];
foreach ($objects->get(StoreManagerInterface::class)->getStores() as $store) {
    $locales[] = (string) $scopeConfig->getValue('general/locale/code', ScopeInterface::SCOPE_STORE, $store->getId());
}
$locales = array_values(array_unique($locales));
printf("locales: %s\n", implode(' ', $locales));

$themePath = $theme['path'] ?? null;
$themeState = 'none';
if ($themePath !== null) {
    $sources = [
        'registration.php' => sprintf(
            "<?php\n\n\\%s::register(\\%s::THEME, '%s', __DIR__);\n",
            ComponentRegistrar::class,
            ComponentRegistrar::class,
            $themePath
        ),
        'theme.xml' => sprintf(
            "<theme xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\""
            . " xsi:noNamespaceSchemaLocation=\"urn:magento:framework:Config/etc/theme.xsd\">\n"
            . "    <title>%s</title>\n    <parent>%s</parent>\n</theme>\n",
            htmlspecialchars($theme['title'], ENT_XML1),
            htmlspecialchars($theme['parent'], ENT_XML1)
        ),
        'web/css/source/_extend.less' => implode('', array_map(
            static fn (string $name, string $value): string => "@{$name}: {$value};\n",
            array_keys($theme['variables']),
            array_values($theme['variables'])
        )),
    ];
    $directory = 'design/' . $themePath;
    $rewritten = false;
    foreach ($sources as $file => $content) {
        if (!$app->isFile("{$directory}/{$file}") || $app->readFile("{$directory}/{$file}") !== $content) {
            $app->writeFile("{$directory}/{$file}", $content);
            $rewritten = true;
        }
    }
    if ($rewritten) {
        $static->delete($themePath);
        $var->delete('view_preprocessed/pub/static/' . $themePath);
        $changed = true;
    }
    if ((new ComponentRegistrar())->getPath(ComponentRegistrar::THEME, $themePath) === null) {
        ComponentRegistrar::register(ComponentRegistrar::THEME, $themePath, $app->getAbsolutePath($directory));
    }
    $objects->get(ThemeRegistration::class)->register();
    $select = $connection->select()->from($themeTable, 'theme_id');
    foreach ($themeWhere($themePath) as $condition => $value) {
        $select->where($condition, $value);
    }
    $themeId = $connection->fetchOne($select);
    if (!$themeId) {
        fwrite(STDERR, "Magento did not register the theme {$themePath}\n");
        exit(1);
    }
    $wanted[THEME_ID] = (string) $themeId;
    $themeState = 'current';
    foreach ($locales as $locale) {
        if (!$static->isFile("{$themePath}/{$locale}/css/styles-m.css")) {
            $themeState = 'stale';
        }
    }
}
printf("theme: %s\n", $themeState);

$written = [];
foreach ($files as $path => $file) {
    $bytes = file_get_contents($file['source']);
    if ($bytes === false) {
        fwrite(STDERR, "cannot read {$file['source']}\n");
        exit(1);
    }
    $name = sprintf(
        '%s/%s-%s.%s',
        OWNED_NAME,
        pathinfo($file['source'], PATHINFO_FILENAME),
        substr(sha1($bytes), 0, 12),
        pathinfo($file['source'], PATHINFO_EXTENSION)
    );
    $target = "{$file['directory']}/{$name}";
    if (!$media->isFile($target)) {
        $media->writeFile($target, $bytes);
        $changed = true;
    }
    $written[] = $target;
    $wanted[$path] = $name;
}
foreach (array_diff($applied['files'], $written) as $target) {
    if ($media->isFile($target)) {
        $media->delete($target);
        $changed = true;
    }
}

$owned = [];
foreach (array_keys($applied['values'] + $wanted) as $path) {
    $present = $stored($path);
    if ($present !== null && $present !== ($applied['values'][$path] ?? null)) {
        continue;
    }
    if (array_key_exists($path, $wanted)) {
        $owned[$path] = (string) $wanted[$path];
        if ($present !== $owned[$path]) {
            $writer->saveConfig($path, $owned[$path], ScopeConfigInterface::SCOPE_TYPE_DEFAULT, 0);
            $changed = true;
        }
    } elseif ($present !== null) {
        $writer->deleteConfig($path, ScopeConfigInterface::SCOPE_TYPE_DEFAULT, 0);
        $changed = true;
    }
}

if ($applied['theme'] !== null && $applied['theme'] !== $themePath) {
    $connection->delete($themeTable, $themeWhere($applied['theme']));
    $app->delete('design/' . $applied['theme']);
    $static->delete($applied['theme']);
    $var->delete('view_preprocessed/pub/static/' . $applied['theme']);
    $changed = true;
}

$state = ['values' => $owned, 'files' => $written, 'theme' => $themePath];
if ($state != $applied) {
    if ($state == ['values' => [], 'files' => [], 'theme' => null]) {
        $writer->deleteConfig(MARK, ScopeConfigInterface::SCOPE_TYPE_DEFAULT, 0);
    } else {
        $writer->saveConfig(MARK, json_encode($state, JSON_THROW_ON_ERROR), ScopeConfigInterface::SCOPE_TYPE_DEFAULT, 0);
    }
    $changed = true;
}

if ($changed) {
    $objects->get(CacheManager::class)->clean(['config', 'full_page', 'block_html']);
    $objects->get(IndexerRegistry::class)->get('design_config_grid')->reindexAll();
}
echo $changed ? "changed\n" : "unchanged\n";
