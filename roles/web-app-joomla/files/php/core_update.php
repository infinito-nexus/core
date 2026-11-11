<?php
// nocheck: mirrored-unit-test - boots the console application of the live Joomla site and drives its com_installer and com_joomlaupdate models against the site database; nothing in it runs without that site

use Joomla\CMS\Extension\ExtensionHelper;
use Joomla\CMS\Factory;
use Joomla\CMS\Log\Log;
use Joomla\Console\Command\AbstractCommand;
use Joomla\Database\DatabaseInterface;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;

const _JEXEC = 1;

$root = getenv('J_ROOT');
if (!is_string($root) || $root === '') {
    fwrite(STDERR, "J_ROOT must name the Joomla document root\n");
    exit(2);
}

if (file_exists($root . '/defines.php')) {
    require_once $root . '/defines.php';
}

if (!defined('_JDEFINES')) {
    define('JPATH_BASE', $root);
    require_once JPATH_BASE . '/includes/defines.php';
}

require_once JPATH_BASE . '/includes/framework.php';

$container = Factory::getContainer();
$container->alias('session', 'session.cli')
    ->alias('JSession', 'session.cli')
    ->alias(\Joomla\CMS\Session\Session::class, 'session.cli')
    ->alias(\Joomla\Session\Session::class, 'session.cli')
    ->alias(\Joomla\Session\SessionInterface::class, 'session.cli');

$app = $container->get(\Joomla\Console\Application::class);
Factory::$application = $app;

$app->addCommand(new class () extends AbstractCommand {
    protected static $defaultName = 'infinito:core';

    protected function configure(): void
    {
        $this->setDescription('Report, check, prepare and finalise a Joomla core update');
        $this->addArgument('action', InputArgument::REQUIRED, 'version | schema | plugins | finalise');
    }

    protected function doExecute(InputInterface $input, OutputInterface $output): int
    {
        $language = $this->getApplication()->getLanguage();
        foreach (['lib_joomla', '', 'com_installer', 'com_joomlaupdate'] as $extension) {
            $language->load($extension, JPATH_ADMINISTRATOR);
        }

        return match ($input->getArgument('action')) {
            'version' => $this->version($output),
            'schema' => $this->schema($output),
            'plugins' => $this->plugins(preg_split('/\s+/', trim((string) getenv('J_PLUGINS')), -1, PREG_SPLIT_NO_EMPTY), $output),
            'finalise' => $this->finalise($output),
        };
    }

    private function version(OutputInterface $output): int
    {
        $manifest = json_decode((string) ExtensionHelper::getExtensionRecord('joomla', 'file')->manifest_cache, true);
        if (!is_array($manifest) || !isset($manifest['version'])) {
            $output->writeln('<error>files_joomla carries no version in its manifest cache</error>');

            return 1;
        }
        $output->writeln('database-version=' . $manifest['version']);

        return 0;
    }

    private function databaseModel(int $extensionId)
    {
        $app   = $this->getApplication();
        $model = $app->bootComponent('com_installer')->getMVCFactory($app)->createModel('Database', 'Administrator');
        $model->setState('filter.extension_id', $extensionId);

        return $model;
    }

    /** @return list<string> */
    private function schemaErrors(int $extensionId): array
    {
        $item = $this->databaseModel($extensionId)->getItems()[0];

        return $item['errorsCount'] > 0 ? array_map('strip_tags', $item['errorsMessage']) : [];
    }

    private function schema(OutputInterface $output): int
    {
        $coreId = (int) ExtensionHelper::getExtensionRecord('joomla', 'file')->extension_id;
        $errors = $this->schemaErrors($coreId);
        if ($errors === []) {
            $output->writeln('schema ' . JVERSION . ': up to date');

            return 0;
        }

        foreach ($errors as $error) {
            $output->writeln('schema ' . JVERSION . ': ' . $error);
        }
        $this->databaseModel($coreId)->fix([$coreId]);

        $errors = $this->schemaErrors($coreId);
        foreach ($errors as $error) {
            $output->writeln('<error>schema ' . JVERSION . ' after fix: ' . $error . '</error>');
        }
        $output->writeln('schema ' . JVERSION . ': ' . ($errors === [] ? 'fixed' : 'still out of date'));

        return $errors === [] ? 0 : 1;
    }

    /** @param list<string> $pairs */
    private function plugins(array $pairs, OutputInterface $output): int
    {
        $db = Factory::getContainer()->get(DatabaseInterface::class);
        foreach ($pairs as $pair) {
            if (!preg_match('#^([a-z0-9_-]+)/([a-z0-9_-]+)=([01])$#', $pair, $match)) {
                $output->writeln("<error>plugin state '$pair' is not folder/element=0|1</error>");

                return 1;
            }
            [, $folder, $element, $enabled] = $match;
            $where = static fn ($query) => $query
                ->where($db->quoteName('type') . ' = ' . $db->quote('plugin'))
                ->where($db->quoteName('folder') . ' = ' . $db->quote($folder))
                ->where($db->quoteName('element') . ' = ' . $db->quote($element));

            $db->setQuery($where($db->createQuery()
                ->update($db->quoteName('#__extensions'))
                ->set($db->quoteName('enabled') . ' = ' . (int) $enabled)))->execute();
            $state = $db->setQuery($where($db->createQuery()
                ->select($db->quoteName('enabled'))
                ->from($db->quoteName('#__extensions'))))->loadResult();

            if ($state === null && $enabled === '0') {
                $output->writeln("plugin $folder/$element: not installed");
                continue;
            }
            if ((string) $state !== $enabled) {
                $output->writeln("<error>plugin $folder/$element could not be set to enabled=$enabled</error>");

                return 1;
            }
            $output->writeln("plugin $folder/$element: enabled=$state");
        }

        return 0;
    }

    private function finalise(OutputInterface $output): int
    {
        Log::addLogger(['logger' => 'echo'], Log::ALL & ~Log::DEBUG, ['Update']);

        $app   = $this->getApplication();
        $model = $app->bootComponent('com_joomlaupdate')->getMVCFactory($app)->createModel('Update', 'Administrator');

        $finalised = $model->finaliseUpgrade();
        foreach ($model->getErrors() as $error) {
            $output->writeln('<error>finalise: ' . ($error instanceof \Throwable ? $error->getMessage() : (string) $error) . '</error>');
        }
        if (!$finalised || $model->getErrors()) {
            return 1;
        }

        $model->resetUpdateSource();
        foreach ([JPATH_CACHE . '/autoload_psr4.php', JPATH_BASE . '/joomla.xml'] as $leftover) {
            if (is_file($leftover) && !unlink($leftover)) {
                $output->writeln("<error>finalise: cannot remove $leftover</error>");

                return 1;
            }
        }
        $model->purge();
        $output->writeln('finalise: Joomla ' . JVERSION);

        return 0;
    }
});

$app->execute();
