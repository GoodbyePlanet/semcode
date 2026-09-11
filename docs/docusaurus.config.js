// @ts-check

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'semcode',
  tagline: 'Hybrid semantic code search for GitHub repositories',
  favicon: 'img/favicon.ico',

  url: 'https://goodbyeplanet.github.io',
  baseUrl: '/semcode/',

  organizationName: 'GoodbyePlanet',
  projectName: 'semcode',

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/GoodbyePlanet/semcode/tree/main/docs/',
        },
        blog: false,
        theme: {
          customCss: undefined,
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      navbar: {
        title: 'semcode',
        items: [
          {
            href: 'https://github.com/GoodbyePlanet/semcode',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [],
        copyright: `Copyright © ${new Date().getFullYear()} semcode.`,
      },
    }),
};

module.exports = config;
