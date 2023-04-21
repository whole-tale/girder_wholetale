import _ from 'underscore';

import PluginConfigBreadcrumbWidget from 'girder/views/widgets/PluginConfigBreadcrumbWidget';
import UploadWidget from 'girder/views/widgets/UploadWidget';
import FolderModel from 'girder/models/FolderModel';
import View from 'girder/views/View';
import events from 'girder/events';
import { restRequest, getApiRoot } from 'girder/rest';

import ConfigViewTemplate from '../templates/configView.pug';
import '../stylesheets/configView.styl';

var ConfigView = View.extend({
    events: {
        'submit #g-wholetale-config-form': function (event) {
            event.preventDefault();
            this.$('#g-wholetale-error-message').empty();

            this._saveSettings([{
                key: 'wholetale.website_url',
                value: this.$('#wholetale_website_url').val()
            }, {
                key: 'wholetale.dashboard_link_title',
                value: this.$('#wholetale_dashboard_link_title').val()
            }, {
                key: 'wholetale.catalog_link_title',
                value: this.$('#wholetale_catalog_link_title').val()
            }, {
                key: 'wholetale.enable_data_catalog',
                value: this.$('#wholetale_enable_data_catalog').is(':checked')
            }, {
                key: 'wholetale.about_href',
                value: this.$('#wholetale_about_href').val()
            }, {
                key: 'wholetale.contact_href',
                value: this.$('#wholetale_contact_href').val()
            }, {
                key: 'wholetale.bug_href',
                value: this.$('#wholetale_bug_href').val()
            }, {
                key: 'wholetale.logo',
                value: this.logoFileId
            }, {
                key: 'wholetale.instance_cap',
                value: this.$('#wholetale_instance_cap').val()
            }, {
                key: 'wholetale.dataverse_url',
                value: this.$('#wholetale_dataverse_url').val()
            }, {
                key: 'wholetale.dataverse_extra_hosts',
                value: this.$('#wholetale_extra_hosts').val().trim()
            }, {
                key: 'wholetale.external_auth_providers',
                value: this.$('#wholetale_external_auth_providers').val().trim()
            }, {
                key: 'wholetale.external_apikey_groups',
                value: this.$('#wholetale_external_apikey_groups').val().trim()
            }, {
                key: 'wholetale.publisher_repositories',
                value: this.$('#wholetale_publisher_repositories').val().trim()
            }]);
        },

        'click #g-wholetale-logo-reset': function (event) {
            this.logoFileId = null;
            this._updateLogoDisplay();
        }
    },
    initialize: function () {
        this.breadcrumb = new PluginConfigBreadcrumbWidget({
            pluginName: 'WholeTale',
            parentView: this
        });

        var keys = [
            'wholetale.website_url',
            'wholetale.dashboard_link_title',
            'wholetale.catalog_link_title',
            'wholetale.enable_data_catalog',
            'wholetale.about_href',
            'wholetale.contact_href',
            'wholetale.bug_href',
            'wholetale.logo',
            'wholetale.instance_cap',
            'wholetale.dataverse_url',
            'wholetale.dataverse_extra_hosts',
            'wholetale.external_auth_providers',
            'wholetale.external_apikey_groups',
            'wholetale.publisher_repositories'
        ];

        restRequest({
            url: 'system/setting',
            type: 'GET',
            data: {
                list: JSON.stringify(keys),
                default: 'none'
            }
        }).done(_.bind(function (resp) {
            this.settings = resp;
            restRequest({
                url: 'system/setting',
                type: 'GET',
                data: {
                    list: JSON.stringify(keys),
                    default: 'default'
                }
            }).done(_.bind(function (resp) {
                this.defaults = resp;
                restRequest({
                    method: 'GET',
                    url: 'wholetale/assets'
                }).done(_.bind(function (resp) {
                    this.logoFileId = this.settings['wholetale.logo'];

                    this.logoUploader = new UploadWidget({
                        parent: new FolderModel({_id: resp['wholetale.logo']}),
                        parentType: 'folder',
                        title: 'Dashboard Logo',
                        modal: false,
                        multiFile: false,
                        parentView: this
                    });
                    this.listenTo(this.logoUploader, 'g:uploadFinished', (event) => {
                        this.logoFileId = event.files[0].id;
                        this._updateLogoDisplay();
                    });

                    this.render();
                }, this));
            }, this));
        }, this));
    },

    _updateLogoDisplay: function () {
        let logoUrl;
        if (this.logoFileId) {
            logoUrl = `${getApiRoot()}/file/${this.logoFileId}/download?contentDisposition=inline`;
            this.$('.g-wholetale-logo-preview img').attr('src', logoUrl);
        }
    },

    render: function () {
        this.$el.html(ConfigViewTemplate({
            settings: this.settings,
            defaults: this.defaults,
            JSON: window.JSON
        }));
        this.breadcrumb.setElement(this.$('.g-config-breadcrumb-container')).render();

        this.logoUploader
            .render()
            .$el.appendTo(this.$('.g-wholetale-logo-upload-container'));
        this._updateLogoDisplay();

        return this;
    },

    _saveSettings: function (settings) {
        restRequest({
            type: 'PUT',
            url: 'system/setting',
            data: {
                list: JSON.stringify(settings)
            },
            error: null
        }).done(_.bind(function (resp) {
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'Settings saved.',
                type: 'success',
                timeout: 4000
            });
        }, this)).fail(_.bind(function (err) {
            this.$('#g-wholetale-error-message').html(err.responseJSON.message);
        }, this));
    }
});

export default ConfigView;
