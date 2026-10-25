// Modified by Tofu on 2026-10-25 (https://github.com/tofu-gallery/bracket): the GitHub link opens this copy's source
// code. See TOFU.md.
import { Anchor, Container, Group } from '@mantine/core';

import { BrandFooter } from '@components/navbar/_brand';
import { getSourceCodeUrl } from '@services/adapter';
import classes from './footer.module.css';

const links = [
  { link: 'https://docs.bracketapp.nl', label: 'Website' },
  // Tofu (2026-10-25): this copy's own source code instead of upstream's repository.
  { link: getSourceCodeUrl(), label: 'GitHub' },
];

export function DashboardFooter() {
  const items = links.map((link) => (
    <Anchor<'a'> c="dimmed" key={link.label} href={link.link} size="sm">
      {link.label}
    </Anchor>
  ));

  return (
    <div className={classes.footer}>
      <Container className={classes.inner}>
        <BrandFooter />
        <Group className={classes.links}>{items}</Group>
      </Container>
    </div>
  );
}
