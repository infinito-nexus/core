<?php
$zip = new ZipArchive();
if ($zip->open(getenv('J_ZIP'), ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
  fwrite(STDERR, "ZipArchive open failed\n"); exit(1);
}
$base = getenv('J_BUILD_DIR');
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($base, FilesystemIterator::SKIP_DOTS));
foreach ($it as $f) {
  if (!$f->isFile()) continue;
  $rel = ltrim(str_replace($base, '', $f->getPathname()), '/');
  $zip->addFile($f->getPathname(), $rel);
}
$zip->close();
echo "ok\n";
