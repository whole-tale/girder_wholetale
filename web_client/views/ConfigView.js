import _ from 'underscore';

import PluginConfigBreadcrumbWidget from 'girder/views/widgets/PluginConfigBreadcrumbWidget';
import View from 'girder/views/View';
import events from 'girder/events';
import { restRequest } from 'girder/rest';

import ConfigViewTemplate from '../templates/configView.pug';
import '../stylesheets/configView.styl';

var ConfigView = View.extend({
    events: {
        'submit #g-wholetale-config-form': function (event) {
            event.preventDefault();
            this.$('#g-wholetale-error-message').empty();

            this._saveSettings([{
                key: 'wholetale.instance_cap',
                value: this.$('#wholetale_instance_cap').val()
            }, {
                key: 'wholetale.dataverse_url',
                value: this.$('#wholetale_dataverse_url').val()
            }, {
                key: 'wholetale.dataverse_extra_hosts',
                value: this.$('#wholetale_extra_hosts').val().trim()
            }, {
                key: 'wholetale.publishers',
                value: this.$('#wholetale_publishers').val().trim()
            }]);
        },
        'click #wholetale_defaults': function (event) {
            event.preventDefault();
            restRequest({
                url: 'system/setting',
                type: 'GET',
                data: {
                    list: JSON.stringify(this.keys),
                    default: 'default'
                }
            }).done(_.bind(function (resp) {
                this.settings = resp;
                this.render();
            }, this));
        }
    },
    initialize: function () {
        this.breadcrumb = new PluginConfigBreadcrumbWidget({
            pluginName: 'WholeTale',
            parentView: this
        });

        this.keys = [
            'wholetale.instance_cap',
            'wholetale.dataverse_url',
            'wholetale.dataverse_extra_hosts',
            'wholetale.publishers'
        ];

        restRequest({
            url: 'system/setting',
            type: 'GET',
            data: {
                list: JSON.stringify(this.keys),
                default: 'none'
            }
        }).done(_.bind(function (resp) {
            this.settings = resp;
            restRequest({
                url: 'system/setting',
                type: 'GET',
                data: {
                    list: JSON.stringify(this.keys),
                    default: 'default'
                }
            }).done(_.bind(function (resp) {
                this.defaults = resp;
                this.render();
            }, this));
        }, this));
    },

    render: function () {
        this.$el.html(ConfigViewTemplate({
            settings: this.settings,
            defaults: this.defaults,
            JSON: window.JSON
        }));
        this.breadcrumb.setElement(this.$('.g-config-breadcrumb-container')).render();
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
